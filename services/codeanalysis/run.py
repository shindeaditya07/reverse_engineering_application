"""Run Code Analysis over a pinned snapshot, verify every finding, and score it on the key."""

import tempfile
from dataclasses import dataclass
from pathlib import Path

from services.codeanalysis.analyze import Analysis, analyze
from services.discovery.agent import to_claim_inputs
from services.discovery.run import as_produced
from services.evals.corpus import APP
from services.evals.key import KeyFact, load_key
from services.evals.score import Scores, score
from services.evidence import SnapshotReader
from services.ingest.limits import MIB, Limits
from services.ingest.pin import PinnedSource, pin_local
from services.verifier import verify_claim

# The answer-key kinds Code Analysis is built to find. `flow` (callback, promise and async
# chains) and `config` are not built yet, so they are not scored here. `unresolved` has no key
# kind: those are Unknown claims that state what could not be followed (CLM-1.4, CLM-1.7).
KINDS = frozenset({"route", "dead_code", "error_handling"})


@dataclass(frozen=True)
class CodeAnalysisRun:
    pinned_revision: str
    analysis: Analysis
    scores: Scores
    blocked: tuple[tuple[str, tuple[str, ...]], ...]  # (claim id, failed check ids)


def run_analysis(pinned: PinnedSource, facts: list[KeyFact] | None = None) -> CodeAnalysisRun:
    reader = SnapshotReader.from_pinned(pinned)
    found = analyze(reader, [f.path for f in pinned.tree.files])
    blocked = []
    for finding in found.findings:
        verdict = verify_claim(to_claim_inputs(finding, reader), reader)
        if not verdict.passed:
            blocked.append((finding.claim_id, tuple(r.check_id for r in verdict.failures)))
    key = [f for f in (facts if facts is not None else load_key()) if f.kind in KINDS]
    scored = [as_produced(f) for f in found.findings if f.kind in KINDS]
    return CodeAnalysisRun(pinned.revision, found, score(scored, key), tuple(blocked))


def run_on_fixture(store: Path | None = None) -> CodeAnalysisRun:
    limits = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
    if store is not None:
        return run_analysis(pin_local(APP, store, limits))
    with tempfile.TemporaryDirectory() as tmp:
        return run_analysis(pin_local(APP, Path(tmp), limits))
