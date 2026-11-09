"""Write the plan as Markdown and check it (OUT-1.2 to OUT-1.5).

Every evidence line is an accepted claim copied word for word with its key. The wording around
them is fixed. `check` re-reads a finished document and fails if an evidence line is not an
accepted claim verbatim, if a proposal has no evidence, if text of a claim that was not accepted
appears, or if the fixed wording promises safety (OUT-1.4).
"""

import json
import re

from services.documentation import DocClaim
from services.modernization.plan import PHASES, Cite, Plan

STATUS = {"confirmed": "Confirmed", "inferred": "Inferred"}
NOT_A_PROMISE = (
    "Everything below is a proposal drawn from claims a reviewer accepted. It states what the "
    "accepted claims show and what could be considered. It does not say that a migration will be "
    "safe, complete or low in risk, and it was not tested against the application."
)
EVIDENCE = re.compile(r"^ {2}- Evidence: \*\*(Confirmed|Inferred)\*\* (.+) \(claim `([^`]+)`\)$")
PROMISES = re.compile(
    r"\b(safe|safely|guarantee[ds]?|risk-free|no risk|seamless|zero[- ]downtime|"
    r"will not break|without breaking)\b",
    re.I,
)


def _evidence(c: Cite) -> str:
    return f"  - Evidence: **{STATUS[c.status]}** {c.text} (claim `{c.key}`)"


def render(plan: Plan, stamp: str) -> tuple[str, str]:
    """(markdown, map json: proposal or boundary id -> claim keys)."""
    out = [
        "# Modernization proposals",
        "",
        f"**PROPOSAL, not a finding.** {stamp}",
        "",
        NOT_A_PROMISE,
        "",
        f"- {plan.accepted} of {plan.total} claims in this run are accepted. Only those are used.",
        "",
        "## Candidate boundaries (proposal)",
        "",
        "Grouped by the names of routes, tables and files, which is a guess about intent. "
        "Treat it as a starting point for discussion.",
    ]
    mapping: dict[str, list[str]] = {}
    if not plan.boundaries:
        out += ["", "No accepted route claims, so no boundary is proposed."]
    for b in plan.boundaries:
        out += ["", f"### {b.name}", ""]
        out += [f"- Files: {', '.join(f'`{f}`' for f in b.files)}"] if b.files else []
        out += ["- Routes:"] if b.routes else []
        out += [_evidence(c) for c in b.routes]
        out += ["- Tables owned by name:"] if b.tables else ["- No table matches this name."]
        out += [_evidence(c) for c in b.tables]
        mapping[f"boundary:{b.name}"] = [c.key for c in (*b.routes, *b.tables)]
    if plan.shared_tables:
        out += ["", "### Tables no boundary matches", ""]
        out += [_evidence(c) for c in plan.shared_tables]
        mapping["boundary:unassigned"] = [c.key for c in plan.shared_tables]
    out += ["", "## Tech-debt and risk map, in phases (proposal)", ""]
    if not plan.items:
        out += ["No accepted claim gives a basis for a proposal."]
    for phase, title in PHASES.items():
        here = [i for i in plan.items if i.phase == phase]
        if not here:
            continue
        out += [f"### Phase {phase}: {title}", ""]
        for i in here:
            out.append(f"- **{i.id}** [proposal] {i.action}")
            out += [_evidence(c) for c in i.cites]
            mapping[i.id] = [c.key for c in i.cites]
        out.append("")
    out += ["## Unknown dependencies", ""]
    if plan.unknown:
        out += [
            "These claims are not accepted, so nothing above rests on them. Until a reviewer "
            "decides on them the plan does not cover what they describe.",
            "",
        ]
        for kind, keys in plan.unknown.items():
            out.append(f"- {kind} ({len(keys)}): " + ", ".join(f"`{k}`" for k in keys))
    else:
        out.append("None: every claim in this run is accepted.")
    out.append("")
    return "\n".join(out), json.dumps(mapping, indent=2, sort_keys=True) + "\n"


def check(markdown: str, claims: list[DocClaim]) -> list[str]:
    """Problems found in a rendered plan; empty means it meets OUT-1.3 to 1.5."""
    accepted = {c.key: c for c in claims if c.accepted and c.status in STATUS}
    problems = []
    lines = markdown.splitlines()
    for n, line in enumerate(lines):
        if line.lstrip().startswith("- Evidence:"):
            m = EVIDENCE.match(line)
            if m is None:
                problems.append(f"not an evidence line: {line[:80]}")
                continue
            status, text, key = m.groups()
            c = accepted.get(key)
            if c is None:
                problems.append(f"{key} is not an accepted claim")
            elif STATUS[c.status] != status or " ".join(c.text.split()) != text:
                problems.append(f"{key}: text or status differs from the stored claim")
        elif line.startswith("- **P-"):
            nxt = lines[n + 1] if n + 1 < len(lines) else ""
            if not nxt.startswith("  - Evidence:"):
                problems.append(f"proposal without evidence: {line[:40]}")
            if PROMISES.search(line):
                problems.append(f"proposal promises safety: {line[:60]}")
        elif PROMISES.search(line) and not line.startswith(("# ", "- Files")):
            if line != NOT_A_PROMISE and "does not say" not in line:
                problems.append(f"wording promises safety: {line[:60]}")
    for c in claims:
        if c.key not in accepted and " ".join(c.text.split()) in markdown:
            problems.append(f"text of a claim that is not accepted appears: {c.key}")
    return problems
