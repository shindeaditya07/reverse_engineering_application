"""Markdown export of the accepted claims of one run (OUT-1.2).

Only claims whose latest version was accepted are listed. Unknown claims cannot be accepted, so
none can appear (CLM-1.4). The header carries the snapshot revision, run ID and date, and always
states how many claims the run has and how many are accepted, so the list is never read as the
whole picture (REV-3.1). Reviewer names are not exported; the audit trail holds them.
"""

import datetime as dt
import uuid
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.models import Claim, Evidence, Snapshot
from services.review.service import ClaimRow, _evidence, _rows, describe_evidence

_STATUS = {"confirmed": "Confirmed", "inferred": "Inferred", "unknown": "Unknown"}


def _one_line(value: str) -> str:
    return " ".join(value.split())


async def export_markdown(
    session: AsyncSession, run_id: uuid.UUID, *, today: dt.date | None = None
) -> str:
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
    accepted = [r for r in rows if r.decision == "accept"]
    counts = Counter(r.decision or "undecided" for r in rows)
    today = today or dt.datetime.now(dt.UTC).date()

    out = [
        "# Accepted claims",
        "",
        f"- Snapshot: `{snapshot.revision}` ({snapshot.source_kind}, {snapshot.source_ref})",
        f"- Run: `{run_id}`",
        f"- Date: {today.isoformat()}",
        f"- Accepted: {len(accepted)} of {len(rows)} claims in this run "
        f"({counts['reject']} rejected, {counts['edit']} replaced by an edit, "
        f"{counts['undecided']} undecided)",
        "",
        "Each statement below was accepted by a human reviewer. Status is what the analysis could "
        "show: Confirmed by a deterministic analysis or test, Inferred otherwise. Unaccepted "
        "claims are not listed.",
    ]
    by_kind: dict[str, list[ClaimRow]] = defaultdict(list)
    for row in accepted:
        by_kind[row.kind].append(row)
    for kind in sorted(by_kind):
        out += ["", f"## {kind}", ""]
        for row in by_kind[kind]:
            out.append(f"- **{_STATUS[row.status]}** {_one_line(row.text)}  ")
            out.append(f"  Claim `{row.key}` version {row.version}.")
            evidence: list[Evidence] = await _evidence(session, row.version_id)
            for ev in evidence:
                out.append(f"  - Evidence: `{describe_evidence(ev)}`")
    out.append("")
    return "\n".join(out)
