"""python -m services.evals smoke [--out DIR]: the CI smoke eval (spec section 19, item 4).

No model is called. It checks that the verifier catches every seeded bad claim (VER-1.4, AGENTS.md
section 9) and that the scoring pipeline is sound: a run that reproduces the key scores 100%
with no overclaims, and an empty run scores 0. It fails, and so fails CI and the staging deploy,
if either check does not hold. It does not prove any analyzer is good: none exists yet.
"""

import argparse
import sys
from pathlib import Path

from services.evals.key import KEY_PATH, load_key, sha256_of
from services.evals.results import render_report, write_results
from services.evals.score import Produced, Scores, score
from services.evals.verifier_eval import VerifierEval, evaluate_verifier
from services.rules_constants import rule_constants


def oracle_run() -> list[Produced]:
    """Claims that reproduce the key exactly: the harness must score these 100%."""
    return [Produced(f.fact_id, f.kind, f.status, f.spans) for f in load_key() if f.spans]


def check(scores: Scores, empty: Scores, verifier: VerifierEval) -> list[str]:
    problems = []
    target = rule_constants("VER-1.4")["seeded_bad_claims_caught_percent"]
    percent = 100 * verifier.caught.hits / verifier.caught.total
    if percent < target:
        problems.append(f"verifier caught {percent:.0f}% of seeded bad claims, need {target}%")
        problems += [f"  missed {m}" for m in verifier.missed]
    if scores.recall.value != 1.0 or scores.precision.value != 1.0 or scores.overclaims:
        problems.append("scoring a run that reproduces the key did not give 100% and no overclaims")
    if empty.recall.hits != 0 or empty.precision.total != 0:
        problems.append("scoring an empty run did not give zero recall and no claims")
    return problems


def smoke(out: Path | None) -> int:
    facts = load_key()
    scores = score(oracle_run(), facts)
    empty = score([], facts)
    verifier = evaluate_verifier()
    report = render_report(
        "Smoke eval (no model; oracle run against the key)", scores, verifier, None
    )
    print(report)
    problems = check(scores, empty, verifier)
    if out is not None:
        manifest = {
            "kind": "smoke",
            "model": None,
            "prompt_sha256": None,
            "answer_key_sha256": sha256_of(KEY_PATH),
            "problems": problems,
        }
        print(f"Wrote {write_results('smoke', report, manifest, out)}")
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("smoke", help="CI smoke eval; exits 1 on failure")
    one.add_argument("--out", type=Path, help="also write report.md and manifest.json under here")
    args = parser.parse_args(argv)
    return smoke(args.out)


if __name__ == "__main__":
    sys.exit(main())
