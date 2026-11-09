"""Ask the local model for example inputs, never for expected outputs (TST-1.1).

The model reads one function (untrusted text, SEC-2.2) and answers with argument lists. What the
function returns is observed in the sandbox, so a wrong guess by the model cannot become a wrong
assertion. Inputs are checked here: right arity, plain JSON, finite numbers, short, unique, at
most MAX_INPUTS. There is no retry: a reply that gives nothing usable means that function has no
test (reported, TST-1.5).

Not from rules_constants.yaml (mine, flagged): MAX_INPUTS and MAX_INPUT_CHARS.
"""

import json
import re
from dataclasses import dataclass

from services.models import ModelClient, ModelError, Request
from services.sandbox.testable import FunctionTarget

MAX_INPUTS = 5
MAX_INPUT_CHARS = 500
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")

INSTRUCTION = (
    "You help characterize a legacy JavaScript function by choosing example inputs. Reply with "
    'JSON only: {"inputs":[[arg1,arg2]]}, where each inner list is the full argument list for '
    f"one call. Give between 1 and {MAX_INPUTS} calls that exercise different branches, "
    "including one edge case. Use JSON values only. Do not predict what the function returns. "
    "Use only the code.\n"
    "Example. Code:\n1  function ship(weight, express) {\n2    if (weight > 20) { return 15; }\n"
    "3    return express ? 9 : 5;\n4  }\n"
    'Answer: {"inputs":[[25,false],[10,true],[10,false],[20,false]]}'
)


@dataclass(frozen=True)
class Proposal:
    inputs: tuple[list[object], ...]
    discarded: int  # proposed calls that failed the checks
    problem: str | None  # why nothing usable came back, or None


def build_request(target: FunctionTarget) -> Request:
    code = f"file: {target.path}\nfunction: {target.name}\n{target.source}"
    return Request(INSTRUCTION, {"code": code})


def parse_inputs(text: str, target: FunctionTarget) -> Proposal:
    try:
        data = json.loads(_FENCE.sub("", text.strip()))
    except ValueError:
        return Proposal((), 0, "the reply was not the requested JSON")
    rows = data.get("inputs") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return Proposal((), 0, "the reply was not the requested JSON")
    kept: list[list[object]] = []
    seen: set[str] = set()
    dropped = 0
    for row in rows:
        try:
            text_row = json.dumps(row, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError):
            dropped += 1
            continue
        ok = (
            isinstance(row, list)
            and len(row) == len(target.params)
            and len(text_row) <= MAX_INPUT_CHARS
            and text_row not in seen
            and len(kept) < MAX_INPUTS
        )
        if ok:
            seen.add(text_row)
            kept.append(row)
        else:
            dropped += 1
    problem = None if kept else "no proposed call had the right shape"
    return Proposal(tuple(kept), dropped, problem)


async def propose(client: ModelClient, target: FunctionTarget) -> Proposal:
    try:
        done = await client.complete(build_request(target))
    except ModelError as error:
        return Proposal((), 0, f"the model call failed ({type(error).__name__})")
    return parse_inputs(done.text, target)
