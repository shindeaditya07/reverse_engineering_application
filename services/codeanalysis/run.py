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

# The answer-key kinds Code Analysis is built to find. `config` is not built yet, so it is not
# scored here. `unresolved` has no key
# kind: those are Unknown claims that state what could not be followed (CLM-1.4, CLM-1.7).
# `dependency` is scored only for the fact Code Analysis owns: Discovery owns the other
# dependency facts, so scoring them here would count its work as a miss.
KINDS = frozenset({"route", "dead_code", "error_handling", "dependency", "flow"})
OWNED_DEPENDENCY_FACTS = frozenset({"T03-F1"})


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
    key = [
        f
        for f in (facts if facts is not None else load_key())
        if f.kind in KINDS and (f.kind != "dependency" or f.fact_id in OWNED_DEPENDENCY_FACTS)
    ]
    scored = [as_produced(f) for f in found.findings if f.kind in KINDS]
    return CodeAnalysisRun(pinned.revision, found, score(scored, key), tuple(blocked))


def run_on_fixture(store: Path | None = None) -> CodeAnalysisRun:
    limits = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
    if store is not None:
        return run_analysis(pin_local(APP, store, limits))
    with tempfile.TemporaryDirectory() as tmp:
        return run_analysis(pin_local(APP, Path(tmp), limits))
