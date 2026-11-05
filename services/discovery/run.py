"""Run Discovery over a pinned snapshot, verify every finding, and score it on the answer key."""

import tempfile
from dataclasses import dataclass
from pathlib import Path

from services.discovery.agent import Discovery, Finding, discover, to_claim_inputs
from services.evals.corpus import APP
from services.evals.key import KeyFact, Span, load_key
from services.evals.score import Produced, Scores, score
from services.evidence import SnapshotReader
from services.ingest.limits import MIB, Limits
from services.ingest.pin import PinnedSource, pin_local
from services.verifier import verify_claim

# The answer-key kinds Discovery is built to find. The other kinds belong to later agents.
KINDS = frozenset({"dependency", "job", "integration", "provenance", "encoding"})


@dataclass(frozen=True)
class DiscoveryRun:
    pinned_revision: str
    discovery: Discovery
    scores: Scores
    blocked: tuple[tuple[str, tuple[str, ...]], ...]  # (claim id, failed check ids)


def as_produced(finding: Finding) -> Produced:
    spans = tuple(Span(p, s, e) for p, s, e in finding.evidence)
    spans += tuple(Span(p, s, e, "byte") for p, s, e in finding.byte_evidence)
    return Produced(finding.claim_id, finding.kind, finding.status, spans)


def run_discovery(pinned: PinnedSource, facts: list[KeyFact] | None = None) -> DiscoveryRun:
    reader = SnapshotReader.from_pinned(pinned)
    found = discover(reader, [f.path for f in pinned.tree.files])
    blocked = []
    for finding in found.findings:
        verdict = verify_claim(to_claim_inputs(finding, reader), reader)
        if not verdict.passed:
            blocked.append((finding.claim_id, tuple(r.check_id for r in verdict.failures)))
    key = [f for f in (facts if facts is not None else load_key()) if f.kind in KINDS]
    return DiscoveryRun(
        pinned.revision,
        found,
        score([as_produced(f) for f in found.findings], key),
        tuple(blocked),
    )


def run_on_fixture(store: Path | None = None) -> DiscoveryRun:
    limits = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
    if store is not None:
        return run_discovery(pin_local(APP, store, limits))
    with tempfile.TemporaryDirectory() as tmp:
        return run_discovery(pin_local(APP, Path(tmp), limits))
