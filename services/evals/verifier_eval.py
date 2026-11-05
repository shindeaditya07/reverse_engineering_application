"""Measure the verifier on its seeded corpora (VER-1.4, VER-1.7)."""

import tempfile
from dataclasses import dataclass
from pathlib import Path

from services.evals.corpus import APP, bad_claims, good_claims
from services.evals.score import Rate
from services.evidence import SnapshotReader
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local
from services.verifier import verify_claim


@dataclass(frozen=True)
class VerifierEval:
    caught: Rate
    v10_caught: Rate
    falsely_blocked: Rate
    v10_demotions: Rate  # among good Inferred claims that carry an explanation
    blocked_ids: tuple[str, ...]
    missed: tuple[str, ...]  # "<check>: <claim text>" for each bad claim not caught


def evaluate_verifier() -> VerifierEval:
    limits = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
    with tempfile.TemporaryDirectory() as store:
        reader = SnapshotReader.from_pinned(pin_local(APP, Path(store), limits))
        bad = [(c, check, verify_claim(c, reader)) for c, check in bad_claims(reader)]
        good = [(c, verify_claim(c, reader)) for c in good_claims(reader)]
    caught = [check in {r.check_id for r in v.failures} for _, check, v in bad]
    v10 = [ok for (_, check, _), ok in zip(bad, caught, strict=True) if check == "V-10"]
    explained = [c for c, _ in good if c.status == "inferred" and c.explanation]
    only_v10 = [c for c, v in good if {r.check_id for r in v.failures} == {"V-10"}]
    return VerifierEval(
        caught=Rate(sum(caught), len(bad)),
        v10_caught=Rate(sum(v10), len(v10)),
        falsely_blocked=Rate(sum(not v.passed for _, v in good), len(good)),
        v10_demotions=Rate(len(only_v10), len(explained)),
        blocked_ids=tuple(c.claim_id for c, v in good if not v.passed),
        missed=tuple(
            f"{check}: {c.text}" for (c, check, _), ok in zip(bad, caught, strict=True) if not ok
        ),
    )
