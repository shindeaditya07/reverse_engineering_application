"""How a function call is observed. The Runner is the only thing that executes legacy code, and it
does so only inside the sandbox. This PR has the interface, the strict parser for the harness
reply, and a fake. The Docker runner is part 6b.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

OUTCOMES = ("value", "throws", "unserializable", "async", "nondeterministic")
STATUSES = ("ok", "timeout", "memory", "crash", "bad_output")
MAX_OUTPUT_BYTES = 256_000


@dataclass(frozen=True)
class RunJob:
    module: str
    function: str
    inputs: tuple[Any, ...]  # each an argument list (JSON values)


@dataclass(frozen=True)
class Observation:
    outcome: str
    value: Any = None  # set when outcome == "value"
    error: str | None = None  # constructor name, set when outcome == "throws"


@dataclass(frozen=True)
class RunResult:
    status: str  # anything but "ok" is a failure, never a pass (TST-1.3, NFR-2)
    observations: tuple[Observation, ...] = field(default_factory=tuple)


class Runner(Protocol):
    def run(self, job: RunJob) -> RunResult: ...


def parse_output(stdout: str, expected: int) -> RunResult:
    """The harness reply, or status bad_output. One line, one JSON object, exactly one
    observation per input, only known outcomes. Anything else fails closed."""
    bad = RunResult("bad_output")
    if len(stdout.encode("utf-8", "replace")) > MAX_OUTPUT_BYTES:
        return bad
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        return bad
    try:
        data = json.loads(lines[0])
    except ValueError:
        return bad
    rows = data.get("observations") if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) != expected:
        return bad
    found = []
    for row in rows:
        if not isinstance(row, dict) or row.get("outcome") not in OUTCOMES:
            return bad
        error = row.get("error")
        if error is not None and not isinstance(error, str):
            return bad
        found.append(Observation(row["outcome"], row.get("value"), error))
    return RunResult("ok", tuple(found))


class FakeRunner:
    """Canned results, for tests. Records the jobs it was given."""

    def __init__(self, results: dict[tuple[str, str], RunResult] | RunResult) -> None:
        self._results = results
        self.jobs: list[RunJob] = []

    def run(self, job: RunJob) -> RunResult:
        self.jobs.append(job)
        if isinstance(self._results, RunResult):
            return self._results
        return self._results.get((job.module, job.function), RunResult("crash"))
