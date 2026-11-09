"""python -m services.businessrule <command>

  prompts  --out FILE        write every prompt the fixture run will send ({hash: prompt}).
                             scripts/record_replies.py sends them to a local model on any machine
                             and writes a recording, so recording does not need this platform.
  run      --recording FILE  replay a recording over the fixture and print the score (no model).
  live     [--record FILE]   send the prompts to the local model in MODEL_ENDPOINT, optionally
                             saving a recording. Never run in CI (SEC-2.3).

The score is printed as it comes out. It is never tuned.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from services.api.settings import get_settings
from services.businessrule.candidates import find_candidates
from services.businessrule.prompt import build_request
from services.businessrule.run import RuleRun, pin_fixture, run_analysis
from services.discovery.inventory import build_inventory
from services.evals.key import load_key
from services.evidence import SnapshotReader
from services.models import LocalClient, ModelClient, RecordedClient, RecordingClient
from services.models.client import prompt_hash


def candidate_coverage() -> tuple[int, int, list[str]]:
    """Key rule/validation facts whose cited lines overlap a candidate. Needs no model."""
    with tempfile.TemporaryDirectory() as tmp:
        pinned = pin_fixture(Path(tmp))
        reader = SnapshotReader.from_pinned(pinned)
        paths = [f.path for f in pinned.tree.files]
        found, _ = find_candidates(reader, list(build_inventory(reader, paths).first_party_sources))
    facts = [f for f in load_key() if f.kind in ("rule", "validation") and f.spans]
    missed = [
        f.fact_id
        for f in facts
        if not any(
            s.file == c.path and s.start <= c.end and c.start <= s.end
            for s in f.spans
            for c in found
        )
    ]
    return len(facts) - len(missed), len(facts), missed


def report(result: RuleRun) -> str:
    scores = result.scores
    findings = result.analysis.findings
    by_status: dict[str, int] = {}
    for f in findings:
        by_status[f.status] = by_status.get(f.status, 0) + 1
    hit, total, missed = candidate_coverage()
    lines = [
        "# Business Rule agent on the fixture",
        "",
        f"- Candidates found (no model): {len(result.analysis.candidates)}",
        f"- Key facts inside a candidate (the ceiling for recall): {hit}/{total}"
        f" (not covered: {', '.join(missed) or 'none'})",
        f"- Recall on rule and validation facts: {scores.recall.show()}",
        f"- Precision: {scores.precision.show()} (a floor: the key lists only the trap facts)",
        f"- Missed facts: {', '.join(scores.missed_facts) or 'none'}",
        f"- Model rules discarded (line outside span, empty, too long): {result.analysis.dropped}",
        f"- Claims blocked by the verifier: {len(result.blocked)} of {len(findings)}",
        f"- Claims by status: "
        f"{', '.join(f'{n} {s}' for s, n in sorted(by_status.items())) or 'none'}",
        "",
        "## Reading this",
        "",
        "- Candidate signals were written after the fixture was read: optimistic.",
        "- Matching is by kind and cited lines, not by whether the sentence is true. A human "
        "must still check the wording against the code.",
    ]
    return "\n".join(lines) + "\n"


def prompts(out: Path) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        pinned = pin_fixture(Path(tmp))
        reader = SnapshotReader.from_pinned(pinned)
        paths = [f.path for f in pinned.tree.files]
        found, _ = find_candidates(reader, list(build_inventory(reader, paths).first_party_sources))
    table = {prompt_hash(r.prompt()): r.prompt() for r in map(build_request, found)}
    out.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(table)


async def execute(client: ModelClient) -> RuleRun:
    with tempfile.TemporaryDirectory() as tmp:
        return await run_analysis(pin_fixture(Path(tmp)), client)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m services.businessrule")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prompts").add_argument("--out", type=Path, required=True)
    sub.add_parser("run").add_argument("--recording", type=Path, required=True)
    sub.add_parser("live").add_argument("--record", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "prompts":
        print(f"wrote {prompts(args.out)} prompts to {args.out}")
        return 0
    if args.cmd == "run":
        client: ModelClient = RecordedClient(args.recording)
    else:
        settings = get_settings()
        client = LocalClient(settings.model_endpoint, settings.model_name)
        if args.record:
            client = RecordingClient(client, args.record, settings.model_name)
    print(report(asyncio.run(execute(client))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
