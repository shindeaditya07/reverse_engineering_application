"""Keep or drop each observation, and write the test (TST-1.1, TST-1.3, TST-1.4, TST-1.5).

Only an observed outcome is kept: a returned value or a thrown error class. A call that timed out,
ran out of memory, crashed, printed anything but the harness reply, returned something that
cannot be stored as JSON, was asynchronous, or gave different answers on two identical calls is
dropped with a fixed reason, never counted as a pass. A kept test whose text holds a secret or
personal data is dropped too (SEC-1.3, SEC-1.5). The test asserts exactly what was observed and
nothing the model said.

`passed` stays None until the generated file is run against the original in the sandbox (6b).
"""

import json
import re
from dataclasses import dataclass, field

from services.ingest.scan import scan_text
from services.sandbox.propose import Proposal
from services.sandbox.runner import RunResult
from services.sandbox.testable import FunctionTarget

RUN_FAILURES = {
    "timeout": "the run exceeded the time limit",
    "memory": "the run exceeded the memory limit",
    "crash": "the run crashed",
    "bad_output": "the harness reply was not in the expected form",
}
OUTCOME_DROPS = {
    "async": "the function is asynchronous",
    "unserializable": "the result cannot be stored as JSON",
    "nondeterministic": "two identical calls gave different results",
}
_ERROR = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


@dataclass(frozen=True)
class Kept:
    target: FunctionTarget
    args: list[object]
    outcome: str  # "value" or "throws"
    value: object = None
    error: str | None = None


@dataclass
class Report:
    """TST-1.5: tests kept, passed and dropped, each drop with its reason."""

    kept: list[Kept] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (function, reason)
    passed: int | None = None

    def text(self) -> str:
        passed = "not run" if self.passed is None else str(self.passed)
        out = [
            f"Tests kept: {len(self.kept)}",
            f"Tests passed: {passed}",
            f"Tests dropped: {len(self.dropped)}",
        ]
        out += [f"- {fn}: {why}" for fn, why in self.dropped]
        return "\n".join(out) + "\n"


def _literal(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True)


def _call(k: Kept) -> str:
    args = ", ".join(_literal(a) for a in k.args)
    return f"m.{k.target.name}({args})"


def _body(k: Kept) -> str:
    if k.outcome == "throws":
        return f"assert.throws(() => {_call(k)}, {{ name: {_literal(k.error)} }});"
    return f"assert.deepStrictEqual({_call(k)}, {_literal(k.value)});"


def render_test(path: str, kept: list[Kept], stamp: str) -> str:
    """A node:test file for one module. `stamp` is the OUT-1.2 line (snapshot, run, date)."""
    safe_stamp = " ".join(stamp.split()).replace("*/", "* /")
    out = [
        f"// Characterization test: what the original did, nothing else. {safe_stamp}",
        "'use strict';",
        "const test = require('node:test');",
        "const assert = require('node:assert');",
        f"const m = require(require('node:path').join(__dirname, '..', {_literal(path)}));",
        "",
    ]
    for n, k in enumerate(kept, 1):
        out += [f"test({_literal(f'{k.target.name} #{n}')}, () => {{", f"  {_body(k)}", "});", ""]
    return "\n".join(out)


def decide(
    target: FunctionTarget, proposal: Proposal, result: RunResult | None, report: Report
) -> None:
    """Add this function's observations to `report`."""
    name = f"{target.path}:{target.name}"
    if not proposal.inputs:
        report.dropped.append((name, "the model proposed no usable inputs"))
        return
    if result is None or result.status != "ok":
        why = RUN_FAILURES.get(result.status if result else "crash", RUN_FAILURES["crash"])
        report.dropped += [(name, why)] * len(proposal.inputs)
        return
    for args, seen in zip(proposal.inputs, result.observations, strict=True):
        if seen.outcome in OUTCOME_DROPS:
            report.dropped.append((name, OUTCOME_DROPS[seen.outcome]))
            continue
        if seen.outcome == "throws" and not (seen.error and _ERROR.match(seen.error)):
            report.dropped.append((name, RUN_FAILURES["bad_output"]))
            continue
        k = Kept(target, args, seen.outcome, seen.value, seen.error)
        if scan_text("sandbox", render_test(target.path, [k], ""), numbered=False):
            report.dropped.append((name, "the test would hold a secret or personal data"))
            continue
        report.kept.append(k)
