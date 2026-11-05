"""Check the fixture answer key against the fixture app (drift check, build-plan step 9).

The key lists the true facts for 35 traps. This script does not judge whether a fact is
true (only a human review does that). It checks that the key is well formed and still
points at the right place in the fixture, so an edit to either one cannot drift silently:

1. Traps 1 to 35 each appear once and have at least one fact.
2. Fact ids are unique and match their trap. Status is Confirmed, Inferred or Unknown.
   Confirmed and Inferred facts cite evidence; only Unknown may have none.
3. Every evidence item is inside the fixture folder, exists, is at most
   max_excerpt_lines long (EVD-1.4), and its snippet starts the stripped text of its first
   line. Lines count after CRLF is normalised to LF (EVD-1.5). A file that is not valid
   UTF-8 must be cited by byte range.
4. A fact is `needs_review` until a human sets `reviewed` with reviewed_by and reviewed_on.
   The top-level `review` may say `reviewed` only when every fact does.

Exit code 0 means the key is consistent, not that it has been reviewed.
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

DEFAULT_KEY = Path("fixtures/answer-key/key.yaml")
CONSTANTS = Path("rules_constants.yaml")
TRAP_COUNT = 35
STATUSES = {"Confirmed", "Inferred", "Unknown"}
REVIEWS = {"needs_review", "reviewed"}
FACT_ID = re.compile(r"^T(\d{2})-F(\d+)$")


def max_excerpt_lines(constants_path: Path = CONSTANTS) -> int:
    constants = yaml.safe_load(constants_path.read_text(encoding="utf-8"))
    return int(constants["EVD-1.4"]["max_excerpt_lines"])


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _check_evidence(item: Any, where: str, app_dir: Path, max_lines: int) -> list[str]:
    if not isinstance(item, dict):
        return [f"{where}: evidence item must be a mapping"]
    name = item.get("file")
    if not isinstance(name, str) or not name:
        return [f"{where}: evidence needs a file"]
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        return [f"{where}: {name} must be a relative path inside the fixture app"]
    path = app_dir / relative
    if not path.is_file():
        return [f"{where}: {name} does not exist in the fixture app"]
    raw = path.read_bytes()

    if "bytes" in item:
        span = item["bytes"]
        if not isinstance(span, dict):
            return [f"{where}: bytes must be a mapping with start, end and hex"]
        start, end, hexed = span.get("start"), span.get("end"), span.get("hex")
        if not (isinstance(start, int) and isinstance(end, int) and isinstance(hexed, str)):
            return [f"{where}: bytes needs integer start and end and a hex string"]
        if not 0 <= start < end <= len(raw):
            return [f"{where}: byte range {start}-{end} is outside {name} ({len(raw)} bytes)"]
        if raw[start:end].hex() != hexed:
            return [
                f"{where}: bytes {start}-{end} of {name} are "
                f"{raw[start:end].hex()}, key says {hexed}"
            ]
        return []

    try:
        text = _normalise(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return [f"{where}: {name} is not valid UTF-8, cite it by byte range"]
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    start, end, snippet = item.get("start"), item.get("end"), item.get("snippet")
    if not (isinstance(start, int) and isinstance(end, int)):
        return [f"{where}: evidence needs integer start and end lines"]
    if not isinstance(snippet, str) or not snippet:
        return [f"{where}: evidence needs a snippet"]
    if not 1 <= start <= end <= len(lines):
        return [f"{where}: lines {start}-{end} are outside {name} ({len(lines)} lines)"]
    if end - start + 1 > max_lines:
        return [f"{where}: {end - start + 1} lines is over the limit of {max_lines} (EVD-1.4)"]
    if not lines[start - 1].strip().startswith(snippet):
        return [f"{where}: line {start} of {name} is {lines[start - 1].strip()!r}, not {snippet!r}"]
    return []


def _check_fact(fact: Any, trap: int, app_dir: Path, max_lines: int) -> list[str]:
    if not isinstance(fact, dict):
        return [f"trap {trap}: a fact must be a mapping"]
    fid = fact.get("id")
    where = f"fact {fid}"
    errors: list[str] = []
    match = FACT_ID.match(fid) if isinstance(fid, str) else None
    if match is None or int(match.group(1)) != trap:
        errors.append(f"trap {trap}: fact id {fid!r} must look like T{trap:02d}-F1")
    if not fact.get("kind"):
        errors.append(f"{where}: kind is required")
    if not fact.get("statement"):
        errors.append(f"{where}: statement is required")
    status = fact.get("status")
    if status not in STATUSES:
        errors.append(f"{where}: status must be one of {sorted(STATUSES)}")
    review = fact.get("review")
    if review not in REVIEWS:
        errors.append(f"{where}: review must be one of {sorted(REVIEWS)}")
    elif review == "reviewed" and not (fact.get("reviewed_by") and fact.get("reviewed_on")):
        errors.append(f"{where}: reviewed needs reviewed_by and reviewed_on")
    evidence = fact.get("evidence") or []
    if not isinstance(evidence, list):
        return [*errors, f"{where}: evidence must be a list"]
    if status in {"Confirmed", "Inferred"} and not evidence:
        errors.append(f"{where}: {status} facts need evidence")
    for number, item in enumerate(evidence, start=1):
        errors.extend(_check_evidence(item, f"{where} evidence {number}", app_dir, max_lines))
    return errors


def check(key: dict[str, Any], repo_root: Path, max_lines: int) -> list[str]:
    """Return every problem found in the key. An empty list means it is consistent."""
    errors: list[str] = []
    if key.get("version") != 1:
        errors.append("version must be 1")
    if key.get("review") not in REVIEWS:
        errors.append(f"review must be one of {sorted(REVIEWS)}")
    app = key.get("app")
    app_dir = repo_root / app if isinstance(app, str) else None
    if app_dir is None or not app_dir.is_dir():
        return [*errors, f"app folder {app!r} does not exist"]

    traps = key.get("traps")
    if not isinstance(traps, list):
        return [*errors, "traps must be a list"]
    numbers = [t.get("trap") if isinstance(t, dict) else None for t in traps]
    if (
        sorted(n for n in numbers if isinstance(n, int)) != list(range(1, TRAP_COUNT + 1))
        or len(numbers) != TRAP_COUNT
    ):
        errors.append(
            f"traps must be numbered 1 to {TRAP_COUNT}, each exactly once (got {numbers})"
        )

    seen_ids: set[str] = set()
    reviews: list[str] = []
    for trap in traps:
        if not isinstance(trap, dict) or not isinstance(trap.get("trap"), int):
            continue
        number = trap["trap"]
        if not trap.get("name"):
            errors.append(f"trap {number}: name is required")
        facts = trap.get("facts") or []
        if not facts:
            errors.append(f"trap {number}: needs at least one fact")
        for fact in facts:
            errors.extend(_check_fact(fact, number, app_dir, max_lines))
            if isinstance(fact, dict):
                fid = fact.get("id")
                if fid in seen_ids:
                    errors.append(f"fact id {fid} is used twice")
                if isinstance(fid, str):
                    seen_ids.add(fid)
                reviews.append(str(fact.get("review")))
    if key.get("review") == "reviewed" and any(r != "reviewed" for r in reviews):
        errors.append("top-level review is 'reviewed' but some facts are still needs_review")
    return errors


def summarise(key: dict[str, Any]) -> str:
    facts = [f for t in key["traps"] for f in t["facts"]]
    status = Counter(f["status"] for f in facts)
    review = Counter(f["review"] for f in facts)
    text = (
        f"{len(key['traps'])} traps, {len(facts)} facts "
        f"(Confirmed {status['Confirmed']}, Inferred {status['Inferred']}, "
        f"Unknown {status['Unknown']}); "
        f"needs_review {review['needs_review']}, reviewed {review['reviewed']}."
    )
    if review["needs_review"]:
        text += " The key is NOT fully reviewed, so scores against it are provisional."
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    args = parser.parse_args(argv)
    key = yaml.safe_load(args.key.read_text(encoding="utf-8"))
    if not isinstance(key, dict):
        print(f"{args.key} must hold a mapping")
        return 1
    errors = check(key, Path("."), max_excerpt_lines())
    if errors:
        print(f"Answer key check failed with {len(errors)} problem(s):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("Answer key check passed. " + summarise(key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
