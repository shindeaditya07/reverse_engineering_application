"""Review decisions on stored claims.

Rules this module enforces, each with a test:
- Nothing is accepted automatically (REV-1.1): every decision is one explicit call naming one
  claim version and one reviewer. A batch is a loop of single decisions.
- Accept, edit and reject are recorded with reviewer, time and reason, append-only (REV-1.2),
  and each writes an audit entry whose detail holds IDs and flags, never text (NFR-5).
- Only the latest version of a claim can be decided. An older version is history.
- Unknown cannot be accepted (CLM-1.4): edit it with evidence, or reject it.
- Accept re-verifies the stored claim against the pinned snapshot and fails closed: a claim whose
  cited bytes changed, or that fails any check, is refused (VER-1.3). Withheld text (V-9) is
  never accepted.
- Edit stores a new version, produced by a human, status Inferred, and verifies it again
  (REV-1.3). It is not accepted by the edit; it needs its own accept. A failed check stores it
  Unknown and queued, as the writer does for any claim.
- A reason or an edited text that matches a secret pattern is refused, not stored (SEC-1.3).
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from services.claims.writer import WITHHELD_TEXT, add_version
from services.db.models import (
    AuditLog,
    Claim,
    ClaimVersion,
    Evidence,
    ReviewDecision,
    ReviewItem,
)
from services.evidence import FileRange, SnapshotReader, parse_ref, ref_from_row, resolve
from services.ingest.scan import scan_text
from services.verifier import ClaimInput, EvidenceInput, verify_claim

DECISIONS = ("accept", "edit", "reject")
VIEWS = ("queue", "undecided", "decided", "all")
MAX_REVIEWER = 64
MAX_REASON = 1000
MAX_TEXT = 4000


class ReviewError(Exception):
    """A decision was refused. Nothing was stored. The message says why and what to do."""


@dataclass(frozen=True)
class ClaimRow:
    version_id: uuid.UUID
    claim_id: uuid.UUID
    run_id: uuid.UUID
    key: str
    kind: str
    version: int
    status: str
    text: str
    queue_reason: str | None  # set while an open review item exists for this version
    decision: str | None  # the latest decision on this version, if any


@dataclass(frozen=True)
class EvidenceView:
    ref: str
    excerpt: str | None  # None: not shown, see `note`
    note: str | None


@dataclass(frozen=True)
class ShowView:
    row: ClaimRow
    producer: str
    producer_kind: str
    failed_checks: tuple[str, ...]
    evidence: tuple[EvidenceView, ...]


@dataclass(frozen=True)
class Decided:
    decision: str
    version_id: uuid.UUID  # the version decided
    new_version_id: uuid.UUID | None  # edit only: the version the edit created
    new_status: str | None  # edit only: the status it was stored with


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _clean(value: str | None, *, what: str, limit: int) -> str:
    value = (value or "").strip()
    if len(value) > limit:
        raise ReviewError(f"{what} is longer than {limit} characters")
    kinds = sorted({f.kind for f in scan_text("review", value, numbered=False)})
    if kinds:
        raise ReviewError(f"{what} holds {', '.join(kinds)}; remove it (SEC-1.3, SEC-1.5)")
    return value


_LATEST = (
    select(ClaimVersion.claim_id, func.max(ClaimVersion.version).label("v"))
    .group_by(ClaimVersion.claim_id)
    .subquery()
)


async def _latest_decisions(
    session: AsyncSession, version_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not version_ids:
        return {}
    rows = (
        await session.execute(
            select(ReviewDecision.claim_version_id, ReviewDecision.decision)
            .where(ReviewDecision.claim_version_id.in_(version_ids))
            .order_by(ReviewDecision.decided_at, ReviewDecision.id)
        )
    ).all()
    return {version_id: decision for version_id, decision in rows}  # the last one wins


async def _rows(session: AsyncSession, *where: Any, limit: int | None = None) -> list[ClaimRow]:
    query = (
        select(ClaimVersion, Claim)
        .join(Claim, Claim.id == ClaimVersion.claim_id)
        .join(
            _LATEST,
            (_LATEST.c.claim_id == ClaimVersion.claim_id) & (_LATEST.c.v == ClaimVersion.version),
        )
        .where(*where)
        .order_by(Claim.kind, Claim.key)
    )
    if limit is not None:
        query = query.limit(limit)
    found = (await session.execute(query)).all()
    ids = [v.id for v, _ in found]
    decisions = await _latest_decisions(session, ids)
    open_items = dict(
        (
            await session.execute(
                select(ReviewItem.claim_version_id, ReviewItem.reason).where(
                    ReviewItem.claim_version_id.in_(ids), ReviewItem.status == "open"
                )
            )
        ).all()
        if ids
        else []
    )
    return [
        ClaimRow(
            version_id=v.id,
            claim_id=c.id,
            run_id=c.run_id,
            key=c.key,
            kind=c.kind,
            version=v.version,
            status=v.status,
            text=v.text,
            queue_reason=open_items.get(v.id),
            decision=decisions.get(v.id),
        )
        for v, c in found
    ]


async def list_claims(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None = None,
    view: str = "queue",
    limit: int | None = None,
) -> list[ClaimRow]:
    """Latest versions only. `queue` is REV-2.1: open review items. `undecided` is every claim
    with no decision yet, so Confirmed claims, which are not queued, can be reviewed too."""
    if view not in VIEWS:
        raise ReviewError(f"view must be one of {', '.join(VIEWS)}")
    where: list[Any] = []
    if run_id is not None:
        where.append(Claim.run_id == run_id)
    if view == "queue":
        where.append(
            ClaimVersion.id.in_(
                select(ReviewItem.claim_version_id).where(ReviewItem.status == "open")
            )
        )
        return await _rows(session, *where, limit=limit)
    rows = await _rows(session, *where)
    if view == "undecided":
        rows = [r for r in rows if r.decision is None]
    elif view == "decided":
        rows = [r for r in rows if r.decision is not None]
    return rows[:limit] if limit is not None else rows


async def resolve_version_id(session: AsyncSession, given: str) -> uuid.UUID:
    """A full ID or a unique prefix of at least 8 characters."""
    given = given.strip().lower()
    try:
        return uuid.UUID(given)
    except ValueError:
        pass
    if len(given) < 8 or any(c not in "0123456789abcdef-" for c in given):
        raise ReviewError("give the full ID or at least 8 hex characters of it")
    found = (
        (
            await session.execute(
                select(ClaimVersion.id)
                .where(text("claim_versions.id::text like :p"))
                .params(p=given + "%")
            )
        )
        .scalars()
        .all()
    )
    if not found:
        raise ReviewError(f"no claim version starts with {given!r}")
    if len(found) > 1:
        raise ReviewError(f"{given!r} matches {len(found)} versions; give more characters")
    return found[0]


async def _version(session: AsyncSession, version_id: uuid.UUID) -> tuple[ClaimVersion, Claim]:
    found = (
        await session.execute(
            select(ClaimVersion, Claim)
            .join(Claim, Claim.id == ClaimVersion.claim_id)
            .where(ClaimVersion.id == version_id)
        )
    ).one_or_none()
    if found is None:
        raise ReviewError(f"claim version {version_id} does not exist")
    return found[0], found[1]


async def _latest_number(session: AsyncSession, claim_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.max(ClaimVersion.version)).where(ClaimVersion.claim_id == claim_id)
        )
    ).scalar_one()


async def _evidence(session: AsyncSession, version_id: uuid.UUID) -> list[Evidence]:
    return list(
        (
            await session.execute(
                select(Evidence)
                .where(Evidence.claim_version_id == version_id)
                .order_by(Evidence.path, Evidence.start_line, Evidence.id)
            )
        )
        .scalars()
        .all()
    )


def describe_evidence(row: Evidence) -> str:
    if row.start_line is not None:
        end = f"-{row.end_line}" if row.end_line not in (None, row.start_line) else ""
        where = f":{row.start_line}{end}"
    elif row.start_byte is not None:
        where = f" bytes {row.start_byte}-{row.end_byte}"
    else:
        where = ""
    name = f" {row.object_name}" if row.object_name else ""
    return f"{row.path}{where}{name} [{row.kind}]"


async def show(
    session: AsyncSession, version_id: uuid.UUID, reader: SnapshotReader | None
) -> ShowView:
    """One claim version with its evidence. An excerpt is shown only if it resolves against the
    snapshot and matches no secret pattern; the claim may be withheld for that very reason."""
    version, claim = await _version(session, version_id)
    row = await _rows(session, ClaimVersion.id == version_id)
    summary = row[0] if row else None
    if summary is None:  # an older version: build the row without queue state
        decisions = await _latest_decisions(session, [version_id])
        summary = ClaimRow(
            version_id, claim.id, claim.run_id, claim.key, claim.kind, version.version,
            version.status, version.text, None, decisions.get(version_id),
        )  # fmt: skip
    failed = (
        await session.execute(
            text(
                "select check_id from verification_results "
                "where claim_version_id = :v and not passed order by check_id"
            ),
            {"v": version_id},
        )
    ).scalars()
    views: list[EvidenceView] = []
    for ev in await _evidence(session, version_id):
        excerpt, note = None, None
        if reader is None:
            note = "snapshot not available"
        else:
            try:
                found = resolve(ref_from_row(ev), reader)
            except Exception as error:
                found = None
                note = f"cannot resolve: {type(error).__name__}"
            if found is not None:
                if found.status != "resolved":
                    note = f"{found.status}: {found.reason}"
                elif scan_text("excerpt", found.excerpt, numbered=False):
                    note = "excerpt withheld: it matches a secret pattern (V-9)"
                else:
                    excerpt = found.excerpt
        views.append(EvidenceView(describe_evidence(ev), excerpt, note))
    return ShowView(summary, version.producer, version.producer_kind, tuple(failed), tuple(views))


async def _claim_input(
    session: AsyncSession, version: ClaimVersion, key: str
) -> tuple[ClaimInput, list[Evidence]]:
    rows = await _evidence(session, version.id)
    items = tuple(EvidenceInput(ref_from_row(r), r.content_hash) for r in rows)
    return (
        ClaimInput(
            claim_id=key,
            text=version.text,
            status=version.status,
            producer_kind=version.producer_kind,
            evidence=items,
        ),
        rows,
    )


def _cited(reader: SnapshotReader, cites: Sequence[str]) -> tuple[EvidenceInput, ...]:
    items = []
    for cite in cites:
        try:
            path, _, span = cite.rpartition(":")
            first, _, last = span.partition("-")
            ref = FileRange(path=path, start_line=int(first), end_line=int(last or first))
            found = resolve(parse_ref(ref.model_dump(mode="json")), reader)
        except (ValueError, TypeError) as error:
            raise ReviewError(f"bad citation {cite!r}; use PATH:START-END ({error})") from error
        if found.status != "resolved":
            raise ReviewError(f"citation {cite!r} does not resolve: {found.reason}")
        items.append(EvidenceInput(ref, found.content_hash))
    return tuple(items)


async def decide(
    session: AsyncSession,
    *,
    version_id: uuid.UUID,
    decision: str,
    reviewer: str,
    reason: str | None,
    reader: SnapshotReader,
    new_text: str | None = None,
    cites: Sequence[str] = (),
    now: dt.datetime | None = None,
) -> Decided:
    """Record one decision on one claim version, or raise ReviewError and store nothing."""
    if decision not in DECISIONS:
        raise ReviewError(f"decision must be one of {', '.join(DECISIONS)}")
    reviewer = _clean(reviewer, what="reviewer", limit=MAX_REVIEWER)
    if not reviewer:
        raise ReviewError("a reviewer name is required (REV-1.2)")
    reason = _clean(reason, what="reason", limit=MAX_REASON)
    if decision in ("edit", "reject") and not reason:
        raise ReviewError(f"{decision} needs a reason (REV-1.2)")
    if decision != "edit" and (new_text or cites):
        raise ReviewError("--text and --cite belong to edit only")

    version, claim = await _version(session, version_id)
    latest = await _latest_number(session, claim.id)
    if version.version != latest:
        raise ReviewError(
            f"version {version.version} is not the latest ({latest}); decide that one"
        )

    new_version_id: uuid.UUID | None = None
    new_status: str | None = None
    detail: dict[str, Any] = {
        "claim_id": str(claim.id),
        "key": claim.key,
        "version": version.version,
        "status": version.status,
        "has_reason": bool(reason),
    }

    if decision == "accept":
        if version.status == "unknown":
            raise ReviewError(
                "an Unknown claim cannot be accepted (CLM-1.4): edit it, or reject it"
            )
        if version.text == WITHHELD_TEXT:
            raise ReviewError("the text of this claim was withheld (V-9); it cannot be accepted")
        try:
            claim_input, _ = await _claim_input(session, version, claim.key)
        except ValueError as error:
            raise ReviewError(f"the stored evidence cannot be rebuilt: {error}") from error
        verdict = verify_claim(claim_input, reader)
        if not verdict.passed or verdict.final_status != version.status:
            failed = [r.check_id for r in verdict.failures] + (["stale"] if verdict.stale else [])
            raise ReviewError(
                f"re-verification against the snapshot failed ({', '.join(failed) or 'status'}); "
                "it cannot be accepted"
            )
    elif decision == "edit":
        edited = _clean(new_text, what="edited text", limit=MAX_TEXT)
        if not edited:
            raise ReviewError("edit needs the new text")
        if edited == version.text.strip():
            raise ReviewError("the edited text is the same as the current text")
        try:
            old_input, _ = await _claim_input(session, version, claim.key)
        except ValueError as error:
            raise ReviewError(f"the stored evidence cannot be rebuilt: {error}") from error
        evidence = _cited(reader, cites) if cites else old_input.evidence
        edited_input = ClaimInput(
            claim_id=claim.key,
            text=edited,
            status="inferred",  # a person's wording is never Confirmed (CLM-1.2)
            producer_kind="human",
            evidence=evidence,
        )
        stored = await add_version(
            session,
            based_on=version.id,
            claim=edited_input,
            producer=f"review:{reviewer}",
            reader=reader,
        )
        new_version_id, new_status = stored.version_id, stored.status
        detail.update(new_version_id=str(new_version_id), new_status=new_status, cited=len(cites))

    when = now or _now()
    session.add(
        ReviewDecision(
            claim_version_id=version.id,
            decision=decision,
            reviewer=reviewer,
            reason=reason or None,
            decided_at=when,
        )
    )
    for item in (
        (
            await session.execute(
                select(ReviewItem).where(
                    ReviewItem.claim_version_id == version.id, ReviewItem.status == "open"
                )
            )
        )
        .scalars()
        .all()
    ):
        item.status = "resolved"
    session.add(
        AuditLog(
            actor=reviewer,
            action=f"review.{decision}",
            subject_type="claim_version",
            subject_id=str(version.id),
            detail=detail,
        )
    )
    await session.flush()
    return Decided(decision, version.id, new_version_id, new_status)


async def history(
    session: AsyncSession, *, version_id: uuid.UUID | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """Decisions, newest first, for one claim (all its versions) or the whole store."""
    query = (
        select(ReviewDecision, Claim.key, ClaimVersion.version)
        .join(ClaimVersion, ClaimVersion.id == ReviewDecision.claim_version_id)
        .join(Claim, Claim.id == ClaimVersion.claim_id)
        .order_by(ReviewDecision.decided_at.desc(), ReviewDecision.id)
        .limit(limit)
    )
    if version_id is not None:
        claim_id = (await _version(session, version_id))[1].id
        query = query.where(Claim.id == claim_id)
    return [
        {
            "decided_at": d.decided_at,
            "decision": d.decision,
            "reviewer": d.reviewer,
            "reason": d.reason,
            "key": key,
            "version": number,
            "version_id": d.claim_version_id,
        }
        for d, key, number in (await session.execute(query)).all()
    ]
