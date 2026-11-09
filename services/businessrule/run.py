"""Run the Business Rule agent over a pinned snapshot, verify every claim, and score it."""

import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from services.businessrule.agent import RuleAnalysis, analyze
from services.discovery.agent import Finding
from services.discovery.run import as_produced
from services.evals.corpus import APP
from services.evals.key import KeyFact, load_key
from services.evals.score import Scores, score
from services.evidence import SnapshotReader, parse_ref, resolve
from services.ingest.limits import MIB, Limits
from services.ingest.pin import PinnedSource, pin_local
from services.models import ModelClient
from services.verifier import ClaimInput, EvidenceInput, verify_claim

# The key separates `rule` from `validation`; the finder cannot tell them apart reliably, so both
# are scored as one kind. Facts with no evidence (T18-F2) are not scorable.
KEY_KINDS = frozenset({"rule", "validation"})
SCORED_KIND = "rule"


@dataclass(frozen=True)
class RuleRun:
    pinned_revision: str
    analysis: RuleAnalysis
    scores: Scores
    blocked: tuple[tuple[str, tuple[str, ...]], ...]  # (claim id, failed check ids)


def to_claim_input(finding: Finding, reader: SnapshotReader) -> ClaimInput:
    """A model-produced claim: its sentence is also the explanation V-10 compares to the code."""
    evidence = []
    for path, start, end in finding.evidence:
        ref = {"kind": "file_range", "path": path, "start_line": start, "end_line": end}
        evidence.append(EvidenceInput(ref, resolve(parse_ref(ref), reader).content_hash))
    explanation = finding.text if finding.status == "inferred" else None
    return ClaimInput(
        finding.claim_id,
        finding.text,
        finding.status,
        "model",
        tuple(evidence),
        explanation=explanation,
    )


async def run_analysis(
    pinned: PinnedSource, client: ModelClient, facts: list[KeyFact] | None = None
) -> RuleRun:
    reader = SnapshotReader.from_pinned(pinned)
    found = await analyze(client, reader, [f.path for f in pinned.tree.files])
    blocked = []
    for finding in found.findings:
        verdict = verify_claim(to_claim_input(finding, reader), reader)
        if not verdict.passed:
            blocked.append((finding.claim_id, tuple(r.check_id for r in verdict.failures)))
    key = [
        replace(f, kind=SCORED_KIND)
        for f in (facts if facts is not None else load_key())
        if f.kind in KEY_KINDS
    ]
    produced = [
        as_produced(replace(f, kind=SCORED_KIND)) for f in found.findings if f.kind in KEY_KINDS
    ]
    return RuleRun(pinned.revision, found, score(produced, key), tuple(blocked))


def pin_fixture(store: Path) -> PinnedSource:
    return pin_local(APP, store, Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30))


async def run_on_fixture(client: ModelClient) -> RuleRun:
    with tempfile.TemporaryDirectory() as tmp:
        return await run_analysis(pin_fixture(Path(tmp)), client)
