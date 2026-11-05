"""Run the grep baseline over a pinned snapshot and score it against the answer key."""

import tempfile
from dataclasses import dataclass
from pathlib import Path

from services.baseline.finder import find_in_file, patterns_sha256, source_files
from services.evals.corpus import APP
from services.evals.key import KeyFact, load_key
from services.evals.runner import RunResult, run_analyzer
from services.evals.score import Produced, Scores, score
from services.evidence import SnapshotReader, Unresolved
from services.ingest.limits import MIB, Limits
from services.ingest.pin import PinnedSource, pin_local


@dataclass(frozen=True)
class BaselineRun:
    pinned_revision: str
    run: RunResult
    unscanned: tuple[tuple[str, str], ...]  # (path, reason): stated, never silent (CLM-1.7)
    scores: Scores
    patterns_sha256: str


def run_baseline(pinned: PinnedSource, facts: list[KeyFact] | None = None) -> BaselineRun:
    reader = SnapshotReader.from_pinned(pinned)
    unscanned: list[tuple[str, str]] = []

    def analyze(path: str) -> list[Produced]:
        try:
            return find_in_file(reader, path)
        except Unresolved as error:
            if error.reason != "undecodable":
                raise  # an unreadable or modified file is a failure, not a skipped file
            unscanned.append((path, error.reason))
            return []

    result = run_analyzer(source_files([f.path for f in pinned.tree.files]), analyze)
    return BaselineRun(
        pinned.revision,
        result,
        tuple(unscanned),
        score(result.claims, facts if facts is not None else load_key()),
        patterns_sha256(),
    )


def run_on_fixture(store: Path | None = None) -> BaselineRun:
    limits = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
    if store is not None:
        return run_baseline(pin_local(APP, store, limits))
    with tempfile.TemporaryDirectory() as tmp:
        return run_baseline(pin_local(APP, Path(tmp), limits))
