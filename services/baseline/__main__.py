"""python -m services.baseline [--out evals/results] [--run-id baseline-grep]

Runs the grep baseline on the fixture, prints the score and, with --out, records it under
<out>/YYYY-MM-DD-<run-id>/. The score is recorded as it comes out. It is never tuned.
"""

import argparse
import sys
from pathlib import Path

from services.baseline.finder import PATTERNS
from services.baseline.run import BaselineRun, run_on_fixture
from services.evals.key import KEY_PATH, sha256_of
from services.evals.results import render_report, write_results
from services.evals.score import Rate


def targeted_recall(result: BaselineRun) -> Rate:
    """Recall over only the kinds the baseline tries to find. The headline recall counts every
    kind in the key, most of which the baseline never looks for, so on its own it misleads."""
    kinds = {p.kind for p in PATTERNS}
    rows = [k.recall for k in result.scores.per_kind if k.kind in kinds]
    return Rate(sum(r.hits for r in rows), sum(r.total for r in rows))


def report(result: BaselineRun) -> str:
    text = render_report("Grep baseline on the fixture (no model)", result.scores, None, result.run)
    kinds = ", ".join(sorted({p.kind for p in PATTERNS}))
    lines = [
        text,
        "## Scope",
        "",
        f"The baseline only looks for: {kinds}. Recall on those kinds alone: "
        f"{targeted_recall(result).show()}.",
        "",
        "## Not analysed",
        "",
    ]
    lines += [f"- `{p}`: {r}" for p, r in result.unscanned] or ["- nothing"]
    lines += [
        "",
        "Claims produced: "
        f"{len(result.run.claims)} (every one Inferred; a regex hit is not a parse).",
        "The patterns were written before the first score and are not tuned to the fixture.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="record the result under this results folder")
    parser.add_argument("--run-id", default="baseline-grep")
    args = parser.parse_args(argv)
    result = run_on_fixture()
    text = report(result)
    print(text)
    if args.out is not None:
        manifest = {
            "kind": "baseline",
            "model": None,
            "prompt_sha256": None,
            "patterns_sha256": result.patterns_sha256,
            "answer_key_sha256": sha256_of(KEY_PATH),
            "fixture_revision": result.pinned_revision,
            "run_valid": result.run.valid,
            "claims": len(result.run.claims),
            "recall_on_targeted_kinds": targeted_recall(result).show(),
            "unscanned": [{"path": p, "reason": r} for p, r in result.unscanned],
        }
        print(f"Wrote {write_results(args.run_id, text, manifest, args.out)}")
    return 0 if result.run.valid else 1


if __name__ == "__main__":
    sys.exit(main())
