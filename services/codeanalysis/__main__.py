"""python -m services.codeanalysis [--out evals/results] [--run-id codeanalysis-v1]

Runs Code Analysis on the fixture, prints the score and, with --out, records it under
<out>/YYYY-MM-DD-<run-id>/. The score is recorded as it comes out. It is never tuned.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from services.codeanalysis.analyze import PARSER_VERSIONS
from services.codeanalysis.run import KINDS, CodeAnalysisRun, run_on_fixture
from services.evals.key import KEY_PATH, sha256_of
from services.evals.results import write_results


def analyzer_sha256() -> str:
    """Fingerprint of the analyzer source. A change must be re-run and re-committed."""
    return hashlib.sha256(Path(__file__).with_name("analyze.py").read_bytes()).hexdigest()


def report(result: CodeAnalysisRun) -> str:
    scores = result.scores
    findings = result.analysis.findings
    by_status: dict[str, int] = {}
    for f in findings:
        by_status[f.status] = by_status.get(f.status, 0) + 1
    lines = [
        "# Code Analysis on the fixture (no model)",
        "",
        f"- Recall on its kinds ({', '.join(sorted(KINDS))}): {scores.recall.show()}",
        f"- Precision: {scores.precision.show()} (a floor: the key lists only the trap facts)",
        f"- Missed facts: {', '.join(scores.missed_facts) or 'none'}",
        f"- Unmatched claims: {', '.join(scores.unmatched_claims) or 'none'}",
        f"- Overclaims: {len(scores.overclaims)}",
        f"- Findings blocked by the verifier: {len(result.blocked)} of {len(findings)}",
        f"- Findings by status: "
        f"{', '.join(f'{n} {s}' for s, n in sorted(by_status.items())) or 'none'}",
        f"- Call graph: {len(result.analysis.calls)} resolved call edges (not claims)",
        "",
        "## Per kind",
        "",
    ]
    lines += [
        f"- {k.kind}: recall {k.recall.show()}; precision {k.precision.show()}"
        for k in scores.per_kind
    ]
    lines += ["", "## Not analysed", ""]
    lines += [f"- `{p}`: {r}" for p, r in result.analysis.unanalyzed] or ["- nothing"]
    lines += [
        "",
        "## Reading this",
        "",
        "- The unmatched route claims are real routes the key does not list: the key holds only "
        "the trap facts, so precision here is a floor.",
        "- The analyzer was written after the fixture was read, so this score is optimistic.",
        "- Not built yet, so not scored: `flow` (callback, promise, async chains) and `config`.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="record the result under this results folder")
    parser.add_argument("--run-id", default="codeanalysis-v1")
    args = parser.parse_args(argv)
    result = run_on_fixture()
    text = report(result)
    print(text)
    if args.out is not None:
        manifest = {
            "kind": "codeanalysis",
            "model": None,
            "prompt_sha256": None,
            "analyzer_sha256": analyzer_sha256(),
            "parser": PARSER_VERSIONS,
            "answer_key_sha256": sha256_of(KEY_PATH),
            "fixture_revision": result.pinned_revision,
            "findings": len(result.analysis.findings),
            "blocked_by_verifier": len(result.blocked),
            "recall": result.scores.recall.show(),
            "unanalyzed": [{"path": p, "reason": r} for p, r in result.analysis.unanalyzed],
        }
        print(f"Wrote {write_results(args.run_id, text, manifest, args.out)}")
    return 0 if not result.blocked else 1


if __name__ == "__main__":
    sys.exit(main())
