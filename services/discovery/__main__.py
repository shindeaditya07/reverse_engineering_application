"""python -m services.discovery [--out evals/results] [--run-id discovery-v2]

Runs Discovery on the fixture, prints the inventory and the score and, with --out, records it
under <out>/YYYY-MM-DD-<run-id>/. The score is recorded as it comes out. It is never tuned.
"""

import argparse
import sys
from pathlib import Path

from services.discovery.agent import patterns_sha256
from services.discovery.run import KINDS, DiscoveryRun, run_on_fixture
from services.evals.key import KEY_PATH, sha256_of
from services.evals.results import write_results


def report(result: DiscoveryRun) -> str:
    inv = result.discovery.inventory
    scores = result.scores
    lines = [
        "# Discovery on the fixture (no model)",
        "",
        f"- Recall on Discovery's kinds ({', '.join(sorted(KINDS))}): {scores.recall.show()}",
        f"- Precision: {scores.precision.show()} (a floor: the key lists only the trap facts)",
        f"- Missed facts: {', '.join(scores.missed_facts) or 'none'}",
        f"- Unmatched claims: {', '.join(scores.unmatched_claims) or 'none'}",
        f"- Overclaims: {len(scores.overclaims)}",
        f"- Findings blocked by the verifier: {len(result.blocked)} of "
        f"{len(result.discovery.findings)}",
        "",
        "## Per kind",
        "",
    ]
    lines += [
        f"- {k.kind}: recall {k.recall.show()}; precision {k.precision.show()}"
        for k in scores.per_kind
    ]
    lines += [
        "",
        "## Inventory",
        "",
        f"- Languages: {', '.join(f'{n} {k}' for k, n in inv.languages.items())}",
        f"- Entry point (package.json main): {inv.main or 'none'}; scripts: "
        f"{', '.join(inv.scripts) or 'none'}",
        f"- Declared dependencies: {', '.join(inv.declared) or 'none'}",
        f"- Generated: {', '.join(inv.generated) or 'none'}; vendored: "
        f"{', '.join(inv.vendored) or 'none'}",
        "",
        "## Not analysed",
        "",
    ]
    lines += [f"- `{p}`: {r}" for p, r in result.discovery.unscanned] or ["- nothing"]
    lines += [
        "",
        "The patterns were written after the fixture was read, so this score is optimistic.",
        "Routes, call graphs and data flow are Code Analysis, not Discovery.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="record the result under this results folder")
    parser.add_argument("--run-id", default="discovery-v2")
    args = parser.parse_args(argv)
    result = run_on_fixture()
    text = report(result)
    print(text)
    if args.out is not None:
        manifest = {
            "kind": "discovery",
            "model": None,
            "prompt_sha256": None,
            "patterns_sha256": patterns_sha256(),
            "answer_key_sha256": sha256_of(KEY_PATH),
            "fixture_revision": result.pinned_revision,
            "findings": len(result.discovery.findings),
            "blocked_by_verifier": len(result.blocked),
            "recall": result.scores.recall.show(),
            "unscanned": [{"path": p, "reason": r} for p, r in result.discovery.unscanned],
        }
        print(f"Wrote {write_results(args.run_id, text, manifest, args.out)}")
    return 0 if not result.blocked else 1


if __name__ == "__main__":
    sys.exit(main())
