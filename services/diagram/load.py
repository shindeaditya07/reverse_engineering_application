"""Load the claims of one run for drawing, and write the diagram document (OUT-1.2)."""

import datetime as dt
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.claims import WITHHELD_TEXT
from services.db.models import Claim, Snapshot
from services.diagram.extract import extract
from services.diagram.model import Diagram, DiagramClaim
from services.diagram.render import render
from services.review.service import _rows

DRAWABLE = ("confirmed", "inferred")


async def load_claims(
    session: AsyncSession, run_id: uuid.UUID, *, accepted_only: bool
) -> tuple[list[DiagramClaim], int, str]:
    """(claims to draw, claims in the run, snapshot revision). The latest version of each claim.
    Unknown, withheld and (with accepted_only) undecided or rejected claims are not drawn."""
    rows = await _rows(session, Claim.run_id == run_id)
    if not rows:
        raise LookupError(f"run {run_id} has no claims")
    snapshot = (
        (
            await session.execute(
                select(Snapshot)
                .join(Claim, Claim.snapshot_id == Snapshot.id)
                .where(Claim.run_id == run_id)
            )
        )
        .scalars()
        .first()
    )
    assert snapshot is not None
    keep = [
        DiagramClaim(r.key, r.kind, r.status, r.text)
        for r in rows
        if r.status in DRAWABLE
        and r.text != WITHHELD_TEXT
        and (not accepted_only or r.decision == "accept")
    ]
    return keep, len(rows), snapshot.revision


def document(
    diagrams: list[Diagram],
    omitted: tuple[tuple[str, str], ...],
    *,
    revision: str,
    run_id: uuid.UUID,
    total: int,
    accepted_only: bool,
    today: dt.date,
) -> tuple[str, str]:
    """(markdown, mapping json). The header carries snapshot, run and date and says how much of
    the run is drawn, so a diagram is never read as the whole picture."""
    used = len({k for d in diagrams for keys in d.mapping.values() for k in keys})
    scope = "accepted claims only" if accepted_only else "Confirmed and Inferred claims"
    out = [
        "# Diagrams",
        "",
        f"- Snapshot: `{revision}`",
        f"- Run: `{run_id}`",
        f"- Date: {today.isoformat()}",
        f"- {used} of {total} claims in this run appear in these diagrams ({scope}; Unknown is "
        "never drawn; claims of other kinds, such as dead code or business rules, "
        "are not diagrammed)",
        "",
        "Solid lines come from Confirmed claims, dashed lines from Inferred ones. Every box and "
        "line maps to claims in `diagrams.map.json`. These are generated from stored claims; "
        "nothing here was written by a model.",
        "",
    ]
    for d in diagrams:
        out += [f"## {d.title}", "", "```mermaid", d.mermaid, "```", ""]
    if not diagrams:
        out += ["No diagram could be drawn from these claims.", ""]
    if omitted:
        out += ["## Not drawn", ""] + [f"- `{key}`: {why}" for key, why in omitted] + [""]
    mapping = {d.name: d.mapping for d in diagrams}
    return "\n".join(out), json.dumps(mapping, indent=2, sort_keys=True) + "\n"


def build(claims: list[DiagramClaim]) -> tuple[list[Diagram], tuple[tuple[str, str], ...]]:
    found = extract(claims)
    return render(found), found.omitted
