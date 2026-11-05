"""Run an analyzer over units of work and say whether the run is valid (AGENTS.md section 10).

A unit that raises, including a timeout, is a failure. It is counted on its own and is never
turned into an empty result. Any failure makes the whole run invalid, not a pass, and three
failures in a row stop it.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from services.evals.score import Produced

# AGENTS.md section 10 says "three in a row". It is not a number in rules.md, so it is not in
# rules_constants.yaml; propose adding it to the rules (OPS-1.1 is about job retries).
MAX_CONSECUTIVE_FAILURES = 3


@dataclass(frozen=True)
class Failure:
    unit: str
    error: str  # the exception type only, never its message


@dataclass(frozen=True)
class RunResult:
    claims: tuple[Produced, ...]
    units_run: int
    units_total: int
    failures: tuple[Failure, ...]
    stopped_early: bool

    @property
    def valid(self) -> bool:
        return not self.failures and not self.stopped_early and self.units_run == self.units_total

    @property
    def status(self) -> str:
        if self.valid:
            return "valid"
        reason = "stopped after consecutive failures" if self.stopped_early else "had failures"
        return f"INVALID: run {reason} ({len(self.failures)} failed of {self.units_total} units)"


def run_analyzer(
    units: Iterable[str],
    analyze: Callable[[str], Sequence[Produced]],
    *,
    max_consecutive: int = MAX_CONSECUTIVE_FAILURES,
) -> RunResult:
    todo = list(units)
    claims: list[Produced] = []
    failures: list[Failure] = []
    in_a_row = 0
    run = 0
    stopped = False
    for unit in todo:
        run += 1
        try:
            claims.extend(analyze(unit))
            in_a_row = 0
        except Exception as error:  # a provider error or timeout is a failure, never a pass
            failures.append(Failure(unit, type(error).__name__))
            in_a_row += 1
            if in_a_row >= max_consecutive:
                stopped = True
                break
    return RunResult(tuple(claims), run, len(todo), tuple(failures), stopped)
