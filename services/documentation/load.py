"""Load a run's claims for documentation and write the bundle (OUT-1.2)."""

import datetime as dt
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.claims import WITHHELD_TEXT
from services.db.models import Claim, Snapshot
from services.documentation.assemble import DocClaim, assemble, check
from services.review.service import _rows


async def load_claims(session: AsyncSession, run_id: uuid.UUID) -> tuple[list[DocClaim], str]:
    """(latest version of every claim, snapshot revision). Withheld text (V-9) is left out."""
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
    claims = [
        DocClaim(r.key, r.kind, r.status, r.text, r.decision == "accept", r.queue_reason)
        for r in rows
        if r.text != WITHHELD_TEXT
    ]
    return claims, snapshot.revision


def build(
    claims: list[DocClaim],
    *,
    revision: str,
    run_id: uuid.UUID,
    accepted_only: bool,
    today: dt.date,
) -> dict[str, str]:
    """file name -> content. index.md says how much of the run is documented; map.json lists the
    claim keys behind each document."""
    scope = "accepted claims only" if accepted_only else "Confirmed and Inferred claims"
    stamp = f"Snapshot `{revision}` · Run `{run_id}` · {today.isoformat()} · {scope}"
    docs, unplaced = assemble(claims, stamp=stamp, accepted_only=accepted_only)
    for d in docs:
        problems = check(d.markdown, claims)
        if problems:  # a bug in this module, never a data problem: refuse to write
            raise AssertionError(f"{d.name}: {problems[0]}")
    used = {k for d in docs for k in d.keys}
    index = [
        "# Documentation index",
        "",
        f"- Snapshot: `{revision}`",
        f"- Run: `{run_id}`",
        f"- Date: {today.isoformat()}",
        f"- {len(used)} of {len(claims)} claims in this run appear in these documents ({scope}; "
        "Unknown claims appear only under open questions)",
        "",
        "Every statement in these documents is a stored claim, copied word for word with its "
        "claim key. Nothing was written by a model.",
        "",
        "## Documents",
        "",
    ]
    index += [f"- [{d.title}]({d.name}.md): {len(d.keys)} claims" for d in docs]
    if unplaced:
        index += ["", "## Claims of kinds with no document yet", ""]
        index += [f"- {kind}: {n}" for kind, n in unplaced.items()]
    files = {f"{d.name}.md": d.markdown for d in docs}
    files["index.md"] = "\n".join(index) + "\n"
    files["map.json"] = json.dumps({d.name: list(d.keys) for d in docs}, indent=2) + "\n"
    return files
