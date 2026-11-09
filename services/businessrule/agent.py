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
from dataclasses import dataclass

from services.businessrule.candidates import Candidate, find_candidates
from services.businessrule.prompt import build_request
from services.discovery.agent import Finding
from services.discovery.inventory import build_inventory
from services.evidence import SnapshotReader
from services.models import ModelClient, ModelError

MAX_RULE_CHARS = 300
MAX_RULES_PER_CANDIDATE = 6
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


@dataclass(frozen=True)
class RuleAnalysis:
    findings: tuple[Finding, ...]
    candidates: tuple[Candidate, ...]
    dropped: int  # model rules discarded: line outside the span, empty or too long
    unread: tuple[tuple[str, str], ...]


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


def findings_for(c: Candidate, reply: str) -> tuple[list[Finding], int]:
    """Claims for one candidate from one reply, and how many rules were discarded."""
    rules = parse_reply(reply)
    if rules is None:
        return [_unknown(c, "the model's reply was not the requested JSON")], 0
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
    return out, dropped


async def analyze(client: ModelClient, reader: SnapshotReader, paths: list[str]) -> RuleAnalysis:
    inventory = build_inventory(reader, paths)
    candidates, unread = find_candidates(reader, list(inventory.first_party_sources))
    findings: list[Finding] = []
    dropped = 0
    for cand in candidates:
        try:
            done = await client.complete(build_request(cand))
        except ModelError as error:
            findings.append(_unknown(cand, f"the model call failed ({type(error).__name__})"))
            continue
        made, lost = findings_for(cand, done.text)
        findings += made
        dropped += lost
    for path, reason in unread:
        findings.append(
            Finding(f"br:unread:{path}", "unresolved", "unknown", f"{path} was not read: {reason}.")
        )
    return RuleAnalysis(tuple(findings), tuple(candidates), dropped, tuple(unread))
