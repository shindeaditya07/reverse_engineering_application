"""Check rules_constants.yaml against docs/rules.md and lock rules.md.

1. Every key in the constants file is a rule ID that exists in rules.md.
2. Every value for that rule appears as a number in that rule's passage.
3. Every number in a rule's passage (outside rule IDs, UTF-8 and 0 or 1) is in the constants.
4. rules.md and rules_constants.yaml match the SHA-256 lock, so edits are deliberate:
   bump the version in rules.md, then run `make policy-lock`.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

RULES = Path("docs/rules.md")
CONSTANTS = Path("rules_constants.yaml")
LOCK = Path(".policy_lock.json")

RULE_LINE = re.compile(r"^- \*\*([A-Z]+-\d+\.\d+)\*\*(.*)$")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
ID_TOKEN = re.compile(r"\b[A-Z]+-\d+(?:\.\d+)?\b|\bUTF-8\b|\bApache-2\.0\b|\bV-\d+\b")
TRIVIAL = {0.0, 1.0}


def parse_rules(text: str) -> dict[str, str]:
    """Map rule ID to its passage (the rule line plus any wrapped continuation lines)."""
    rules: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        match = RULE_LINE.match(line)
        if match:
            current = match.group(1)
            rules[current] = match.group(2)
        elif current and line.strip() and not line.startswith(("#", "- ")):
            rules[current] += " " + line.strip()
        else:
            current = None
    return rules


def numbers_in(passage: str) -> set[float]:
    return {float(token) for token in NUMBER.findall(ID_TOKEN.sub(" ", passage))}


def check_constants(rules: dict[str, str], constants: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for rule_id, entries in constants.items():
        if rule_id in ("version", "source"):
            continue
        if rule_id not in rules:
            errors.append(f"{rule_id}: no such rule in rules.md")
            continue
        if not isinstance(entries, dict):
            errors.append(f"{rule_id}: expected a mapping of names to values")
            continue
        present = numbers_in(rules[rule_id])
        for name, value in entries.items():
            if float(value) not in present:
                errors.append(f"{rule_id}.{name}: value {value} not found in the rule text")
    return errors


def check_unconstrained_numbers(rules: dict[str, str], constants: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for rule_id, passage in rules.items():
        entries = constants.get(rule_id)
        allowed = {float(v) for v in entries.values()} if isinstance(entries, dict) else set()
        for number in sorted(numbers_in(passage) - allowed - TRIVIAL):
            errors.append(
                f"{rule_id}: number {number:g} is in the rule text but not in the constants"
            )
    return errors


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_lock(lock_path: Path, files: list[Path]) -> list[str]:
    if not lock_path.exists():
        return [f"{lock_path} is missing; run `make policy-lock`"]
    locked = json.loads(lock_path.read_text())
    errors: list[str] = []
    for path in files:
        if locked.get(str(path)) != digest(path):
            errors.append(
                f"{path} changed since the lock. Bump the version in rules.md, "
                "have the change reviewed, then run `make policy-lock`."
            )
    return errors


def write_lock(lock_path: Path, files: list[Path]) -> None:
    lock_path.write_text(json.dumps({str(p): digest(p) for p in files}, indent=2) + "\n")


def run(rules_path: Path, constants_path: Path, lock_path: Path) -> list[str]:
    rules = parse_rules(rules_path.read_text())
    constants = yaml.safe_load(constants_path.read_text())
    return (
        check_constants(rules, constants)
        + check_unconstrained_numbers(rules, constants)
        + check_lock(lock_path, [rules_path, constants_path])
    )


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--write-lock":
        errors = run_without_lock()
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        write_lock(LOCK, [RULES, CONSTANTS])
        print(f"wrote {LOCK}")
        return 0
    errors = run(RULES, CONSTANTS, LOCK)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("policy check passed")
    return 0


def run_without_lock() -> list[str]:
    rules = parse_rules(RULES.read_text())
    constants = yaml.safe_load(CONSTANTS.read_text())
    return check_constants(rules, constants) + check_unconstrained_numbers(rules, constants)


if __name__ == "__main__":
    raise SystemExit(main())
