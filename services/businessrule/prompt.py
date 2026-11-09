"""The Business Rule prompt. Legacy code goes only inside the delimited block (SEC-2.2).

`INSTRUCTION` is the v2 prompt from scripts/model_benchmark.py (a plain WHEN/THEN sentence per
rule, no copied code, one worked example), plus one added sentence that lets the model answer
with no rules. That addition was NOT part of the benchmarked prompt. Changing the prompt changes
every prompt hash, so recordings must be made again.
"""

from services.businessrule.candidates import Candidate
from services.models import Request

INSTRUCTION = (
    "You document business rules of a legacy app. A business rule is a plain-English "
    "sentence: WHEN some condition holds, THEN this outcome happens. Do not copy code. "
    "Do not list a line that is only a brace or a plain return of an input. "
    'Reply with JSON only: {"rules":[{"text":"<sentence>","line":N}]}, where line is the '
    "number of the line holding the condition. Use only the code. "
    'If the code states no rule, reply {"rules":[]}.\n'
    "Example. Code:\n1  function ship(o) {\n2    if (o.weight > 20) { return 15; }\n"
    "3    return 5;\n4  }\n"
    'Answer: {"rules":[{"text":"Orders heavier than 20 are charged 15 shipping, '
    'otherwise 5.","line":2}]}'
)


def build_request(candidate: Candidate) -> Request:
    return Request(INSTRUCTION, {"code": f"file: {candidate.path}\n{candidate.code}"})
