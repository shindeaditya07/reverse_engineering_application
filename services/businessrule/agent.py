"""Business Rule agent (FR-5): a deterministic finder picks spans, a local model states the rule.

Every rule is an Inferred claim produced by a model (CLM-1.2). Its evidence is the candidate
span the finder chose, never lines the model invented: a rule whose line is outside the span is
dropped. When the model fails or its reply cannot be read, the span becomes an Unknown claim
(CLM-1.4, CLM-1.7). The model's sentence is also the claim's explanation, so V-10 compares it
with the cited code.

The candidate signals were written after the fixture was read, so the fixture score is
optimistic.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from services.businessrule.candidates import Candidate, find_candidates
from services.businessrule.prompt import build_request
from services.discovery.agent import Finding
from services.discovery.inventory import build_inventory
from services.evidence import SnapshotReader
from services.models import ModelClient, ModelError

MAX_RULE_CHARS = 300
MAX_RULES_PER_CANDIDATE = 6
# One retry per candidate. Not in rules_constants.yaml: OPS-1.1 limits job retries, not this.
MAX_RETRIES = 1
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


@dataclass(frozen=True)
class RuleAnalysis:
    findings: tuple[Finding, ...]
    candidates: tuple[Candidate, ...]
    dropped: int  # model rules discarded: line outside the span, empty or too long
    unread: tuple[tuple[str, str], ...]
    retries: int = 0  # extra model calls made after a hard failure


def parse_reply(text: str) -> list[object] | None:
    """The reply's rule list, or None if it is not the requested JSON."""
    try:
        data = json.loads(_FENCE.sub("", text.strip()))
    except ValueError:
        return None
    rules = data.get("rules") if isinstance(data, dict) else data
    return rules if isinstance(rules, list) else None


def _unknown(c: Candidate, why: str) -> Finding:
    return Finding(
        f"br:unexplained:{c.key}",
        "unresolved",
        "unknown",
        f"No business rule was stated for {c.path} lines {c.start}-{c.end}: {why}.",
    )


def parse_rules(c: Candidate, reply: str) -> tuple[list[Finding], int, str | None]:
    """Claims from one reply, how many rules were discarded, and the reason the reply as a
    whole is unusable (None if it is usable). An empty list is a usable answer: no rule."""
    rules = parse_reply(reply)
    if rules is None:
        return [], 0, "the reply was not the requested JSON."
    out: list[Finding] = []
    dropped = 0
    for rule in rules[:MAX_RULES_PER_CANDIDATE]:
        text = rule.get("text") if isinstance(rule, dict) else None
        line = rule.get("line") if isinstance(rule, dict) else None
        ok = (
            isinstance(text, str)
            and 0 < len(text.strip()) <= MAX_RULE_CHARS
            and isinstance(line, int)
            and not isinstance(line, bool)
            and c.start <= line <= c.end
        )
        if not ok:
            dropped += 1
            continue
        assert isinstance(text, str) and isinstance(line, int)
        out.append(
            Finding(
                f"br:{c.path}:{line}:{len(out) + 1}",
                c.kind,
                "inferred",
                text.strip(),
                ((c.path, c.start, c.end),),
            )
        )
    dropped += max(0, len(rules) - MAX_RULES_PER_CANDIDATE)
    if rules and not out:
        return (
            [],
            dropped,
            (f"every rule was empty, too long, or cited a line outside {c.start}-{c.end}."),
        )
    return out, dropped, None


def findings_for(c: Candidate, reply: str) -> tuple[list[Finding], int]:
    """Claims for one candidate from one reply, and how many rules were discarded."""
    made, dropped, problem = parse_rules(c, reply)
    if problem:
        return [_unknown(c, problem.rstrip("."))], dropped
    return made, dropped


async def explain(client: ModelClient, c: Candidate) -> tuple[list[Finding], int, int]:
    """Ask the model about one candidate. Findings, discarded rules, and retries used.

    A hard failure (the call failed, or the reply is unusable as a whole) is retried up to
    MAX_RETRIES times: a failed call again as it was, an unusable reply with the reason added.
    A reply that parses is never retried, even if the verifier later rejects its sentence: the
    same prompt at temperature 0 would give the same sentence. What still fails becomes an
    Unknown claim (CLM-1.4); the claim writer demotes whatever the verifier blocks.
    """
    problem: str | None = None
    why = "no attempt was made"
    for attempt in range(MAX_RETRIES + 1):
        try:
            done = await client.complete(build_request(c, problem))
        except ModelError as error:
            why = f"the model call failed ({type(error).__name__})"
            continue
        made, dropped, problem = parse_rules(c, done.text)
        if problem is None:
            return made, dropped, attempt
        why = problem.rstrip(".")
    return [_unknown(c, why)], 0, MAX_RETRIES


async def analyze(
    client: ModelClient,
    reader: SnapshotReader,
    paths: list[str],
    only: Callable[[str], bool] | None = None,
) -> RuleAnalysis:
    """Explain every candidate, or only those in files `only` accepts (one job per file)."""
    inventory = build_inventory(reader, paths)
    candidates, unread = find_candidates(reader, list(inventory.first_party_sources))
    if only is not None:
        candidates = [c for c in candidates if only(c.path)]
        unread = [(p, r) for p, r in unread if only(p)]
    findings: list[Finding] = []
    dropped = retries = 0
    for cand in candidates:
        made, lost, used = await explain(client, cand)
        findings += made
        dropped += lost
        retries += used
    for path, reason in unread:
        findings.append(
            Finding(f"br:unread:{path}", "unresolved", "unknown", f"{path} was not read: {reason}.")
        )
    return RuleAnalysis(tuple(findings), tuple(candidates), dropped, tuple(unread), retries)
