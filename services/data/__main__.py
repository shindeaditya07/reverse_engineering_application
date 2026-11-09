"""python -m services.data [--out evals/results] [--run-id data-v2]

Runs the Data agent on the fixture, prints the score and, with --out, records it under
<out>/YYYY-MM-DD-<run-id>/. The score is recorded as it comes out. It is never tuned.
"""

import argparse
import hashlib
import sys
from importlib.metadata import version
from pathlib import Path

from services.data.run import KINDS, DataRun, run_on_fixture
from services.evals.key import KEY_PATH, sha256_of
from services.evals.results import write_results

PARSERS = f"sqlglot {version('sqlglot')} (MySQL dialect); tree-sitter-javascript 0.25"
SOURCES = ("agent.py", "pii.py", "schema.py", "sql.py")


def analyzer_sha256() -> str:
    """Fingerprint of the analyzer sources. A change must be re-run and re-committed."""
    digest = hashlib.sha256()
    for name in SOURCES:
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()


def report(result: DataRun) -> str:
    scores = result.scores
    findings = result.analysis.findings
    by_status: dict[str, int] = {}
    for f in findings:
        by_status[f.status] = by_status.get(f.status, 0) + 1
    lines = [
        "# Data agent on the fixture (no model)",
        "",
        f"- Recall on its kinds ({', '.join(sorted(KINDS))}): {scores.recall.show()}",
        f"- Precision: {scores.precision.show()} (a floor: the key lists only the trap facts)",
        f"- Missed facts: {', '.join(scores.missed_facts) or 'none'}",
        f"- Unmatched claims: {', '.join(scores.unmatched_claims) or 'none'}",
        f"- Overclaims: {len(scores.overclaims)}",
        f"- Findings blocked by the verifier: {len(result.blocked)} of {len(findings)}",
        f"- Findings by status: "
        f"{', '.join(f'{n} {s}' for s, n in sorted(by_status.items())) or 'none'}",
        f"- Schema: {len(result.analysis.er.tables)} tables, "
        f"{len(result.analysis.er.relations)} relations; "
        f"{len(result.analysis.sites)} SQL statements resolved",
        "",
        "## Per kind",
        "",
    ]
    lines += [
        f"- {k.kind}: recall {k.recall.show()}; precision {k.precision.show()}"
        for k in scores.per_kind
    ]
    lines += ["", "## Not analysed", ""]
    lines += [f"- `{p}`: {r}" for p, r in result.analysis.unread] or ["- nothing"]
    lines += [
        f"- `{f}` line {a}: a driver call whose SQL is a parameter; its callers are analysed"
        for f, a, _ in result.analysis.plumbing
    ]
    lines += [
        "",
        "## Reading this",
        "",
        "- The unmatched claims are mostly real statements and columns the key does not list: the "
        "key holds only the trap facts, so precision here is a floor.",
        "- The analyzer was written after the fixture was read, so this score is optimistic.",
        "- `pii` is a pattern match (e-mail, phone, SSN-like, card-like, fields named like "
        "personal data) in data-like files. It does not find names or free-text addresses. "
        "The claim cites the nearest line before the first match that matches nothing, because "
        "a cited line with personal data would be withheld by V-9. Status is Inferred.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="record the result under this results folder")
    parser.add_argument("--run-id", default="data-v2")
    args = parser.parse_args(argv)
    result = run_on_fixture()
    text = report(result)
    print(text)
    if args.out is not None:
        manifest = {
            "kind": "data",
            "model": None,
            "prompt_sha256": None,
            "analyzer_sha256": analyzer_sha256(),
            "parsers": PARSERS,
            "answer_key_sha256": sha256_of(KEY_PATH),
            "fixture_revision": result.pinned_revision,
            "findings": len(result.analysis.findings),
            "blocked_by_verifier": len(result.blocked),
            "recall": result.scores.recall.show(),
            "unread": [{"path": p, "reason": r} for p, r in result.analysis.unread],
        }
        print(f"Wrote {write_results(args.run_id, text, manifest, args.out)}")
    return 0 if not result.blocked else 1


if __name__ == "__main__":
    sys.exit(main())
