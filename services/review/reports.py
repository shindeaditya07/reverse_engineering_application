"""Coverage and accuracy reports (REV-3.1 to REV-3.5).

Rules this module enforces, each with a test:
- Coverage is computed from stored decisions, never claimed (REV-3.1). The denominator is always
  printed. A module the parser could not read stays in it as undocumented.
- The accuracy sample is drawn by this script, at random, from claims the reviewer has not yet
  decided, and is recorded in the audit log with its seed. There is one sample per run: a second
  draw is refused, so a bad draw cannot be re-rolled (REV-3.3).
- A sample below the minimum is refused unless the caller says so, and the report then says it
  is below the minimum (REV-3.3).
- Accuracy is the share of sampled claims a human marked correct. Accept counts as correct;
  reject and edit do not (an edit means the claim needed changing). The rate is always printed
  with the sample size and a Wilson 95% interval (REV-3.3).
- The target is met only if the interval's lower bound reaches it. A point estimate that passes
  with a lower bound below the target is reported as not demonstrated (REV-3.4).
- A sample with undecided claims has no verdict (the rate would be of a self-selected subset).
"""

import datetime as dt
import random
import secrets
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.models import AuditLog, Claim, ClaimVersion, Evidence, Snapshot
from services.discovery.inventory import build_inventory
from services.evals.score import Rate
from services.evidence import SnapshotReader
from services.review.service import (
    ClaimRow,
    ReviewError,
    _latest_decisions,
    _rows,
)
from services.rules_constants import rule_constants

SAMPLE_ACTION = "accuracy.sample_drawn"
ASSERTIONS = ("confirmed", "inferred")  # Unknown states what is not known: it is not scored


def _target() -> float:
    return float(rule_constants("REV-3.2")["accuracy_target_percent"]) / 100


def _minimum() -> int:
    return int(rule_constants("REV-3.3")["min_accuracy_sample_claims"])


def _limit() -> int:
    return int(rule_constants("REV-3.5")["max_pilot_claims"])


@dataclass(frozen=True)
class Sample:
    run_id: uuid.UUID
    version_ids: tuple[uuid.UUID, ...]
    seed: int
    eligible: int
    below_minimum: bool
    drawn_by: str
    drawn_at: dt.datetime


async def load_sample(session: AsyncSession, run_id: uuid.UUID) -> Sample | None:
    row = (
        (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.action == SAMPLE_ACTION, AuditLog.subject_id == str(run_id))
                .order_by(AuditLog.id)
            )
        )
        .scalars()
        .first()
    )
    if row is None or row.detail is None:
        return None
    d: dict[str, Any] = row.detail
    return Sample(
        run_id=run_id,
        version_ids=tuple(uuid.UUID(v) for v in d["claim_version_ids"]),
        seed=int(d["seed"]),
        eligible=int(d["eligible"]),
        below_minimum=bool(d["below_minimum"]),
        drawn_by=row.actor,
        drawn_at=row.at,
    )


async def draw_sample(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    drawn_by: str,
    size: int | None = None,
    seed: int | None = None,
    below_minimum: bool = False,
) -> Sample:
    """Draw the accuracy sample for a run, once. Eligible: the latest version of a claim that
    asserts something (Confirmed or Inferred) and has no review decision yet (REV-3.3)."""
    drawn_by = drawn_by.strip()
    if not drawn_by:
        raise ReviewError("a name is required to record who drew the sample")
    if await load_sample(session, run_id) is not None:
        raise ReviewError("this run already has an accuracy sample; it cannot be drawn again")
    rows = await _rows(session, Claim.run_id == run_id)
    if not rows:
        raise LookupError(f"run {run_id} has no claims")
    eligible = sorted(
        (r for r in rows if r.status in ASSERTIONS and r.decision is None),
        key=lambda r: str(r.version_id),
    )
    wanted = size if size is not None else _minimum()
    if wanted < 1:
        raise ReviewError("the sample size must be at least 1")
    if not eligible:
        raise ReviewError("no claim is eligible: all have a decision or are Unknown")
    if wanted > len(eligible):
        if not below_minimum:
            raise ReviewError(
                f"{wanted} claims were asked for and {len(eligible)} are eligible (minimum "
                f"{_minimum()}, REV-3.3). Pass --below-minimum to sample all {len(eligible)}; "
                f"the report will say the sample is below the minimum."
            )
        wanted = len(eligible)
    small = wanted < _minimum()
    if small and not below_minimum:
        raise ReviewError(
            f"the minimum sample is {_minimum()} claims (REV-3.3). Pass --below-minimum to "
            f"draw {wanted}; the report will say the sample is below the minimum."
        )
    used = seed if seed is not None else secrets.randbits(63)
    chosen = random.Random(used).sample(eligible, wanted)
    ids = tuple(r.version_id for r in sorted(chosen, key=lambda r: str(r.version_id)))
    session.add(
        AuditLog(
            actor=drawn_by,
            action=SAMPLE_ACTION,
            subject_type="run",
            subject_id=str(run_id),
            detail={
                "claim_version_ids": [str(i) for i in ids],
                "seed": used,
                "eligible": len(eligible),
                "size": len(ids),
                "below_minimum": small,
            },
        )
    )
    await session.flush()
    sample = await load_sample(session, run_id)
    assert sample is not None
    return sample


@dataclass(frozen=True)
class Accuracy:
    sample: Sample | None
    size: int
    decided: int
    correct: int
    by_status: dict[str, tuple[int, int]]  # status -> (correct, decided)
    undecided: tuple[uuid.UUID, ...]
    rate: Rate
    verdict: str


def _verdict(sample: Sample, undecided: int, rate: Rate) -> str:
    target = _target()
    if undecided:
        return (
            f"INCOMPLETE: {undecided} of {len(sample.version_ids)} sampled claims have no "
            f"decision yet, so there is no verdict."
        )
    if sample.below_minimum or len(sample.version_ids) < _minimum():
        return (
            f"NOT DEMONSTRATED: the sample of {len(sample.version_ids)} is below the minimum of "
            f"{_minimum()} (REV-3.3)."
        )
    low, _ = rate.interval
    if low >= target:
        return (
            f"DEMONSTRATED: the interval's lower bound ({100 * low:.0f}%) reaches the "
            f"{100 * target:.0f}% target."
        )
    passes = rate.value is not None and rate.value >= target
    return (
        f"NOT DEMONSTRATED: the interval's lower bound ({100 * low:.0f}%) is below the "
        f"{100 * target:.0f}% target"
        + (" even though the point estimate passes (REV-3.4)." if passes else " (REV-3.4).")
    )


async def accuracy(session: AsyncSession, run_id: uuid.UUID) -> Accuracy:
    sample = await load_sample(session, run_id)
    if sample is None:
        return Accuracy(None, 0, 0, 0, {}, (), Rate(0, 0), "NO SAMPLE: none has been drawn.")
    ids = list(sample.version_ids)
    decisions = await _latest_decisions(session, ids)
    statuses = await _statuses(session, ids)
    undecided = tuple(i for i in ids if i not in decisions)
    decided = [i for i in ids if i in decisions]
    correct = [i for i in decided if decisions[i] == "accept"]
    by_status: dict[str, tuple[int, int]] = {}
    for status in ASSERTIONS:
        group = [i for i in decided if statuses[i] == status]
        by_status[status] = (sum(1 for i in group if decisions[i] == "accept"), len(group))
    rate = Rate(len(correct), len(decided))
    return Accuracy(
        sample, len(ids), len(decided), len(correct), by_status, undecided, rate,
        _verdict(sample, len(undecided), rate),
    )  # fmt: skip


async def _statuses(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = (
        await session.execute(
            select(ClaimVersion.id, ClaimVersion.status).where(ClaimVersion.id.in_(ids))
        )
    ).all()
    return {i: s for i, s in rows}


@dataclass(frozen=True)
class Coverage:
    modules: Rate
    endpoints: Rate
    uncovered_modules: tuple[str, ...]
    unreadable_modules: tuple[str, ...]  # in the denominator, never covered
    uncovered_endpoints: tuple[str, ...]  # route claim keys


def _overlaps(ev: Evidence, path: str, first: int | None, last: int | None) -> bool:
    if ev.path != path:
        return False
    if first is None or last is None or ev.start_line is None or ev.end_line is None:
        return True
    return ev.start_line <= last and first <= (ev.end_line or ev.start_line)


async def coverage(session: AsyncSession, run_id: uuid.UUID, reader: SnapshotReader) -> Coverage:
    """Modules (first-party source files) and endpoints (route claims) with at least one
    accepted claim citing them, over all found (REV-3.1)."""
    rows = await _rows(session, Claim.run_id == run_id)
    accepted = [r for r in rows if r.decision == "accept"]
    cited: list[Evidence] = []
    if accepted:
        cited = list(
            (
                await session.execute(
                    select(Evidence).where(
                        Evidence.claim_version_id.in_([r.version_id for r in accepted])
                    )
                )
            )
            .scalars()
            .all()
        )
    modules = sorted(build_inventory(reader, reader.paths()).first_party_sources)
    documented = {e.path for e in cited if e.path}
    unreadable = sorted(
        {
            r.key.split(":", 2)[2]
            for r in rows
            if r.key.startswith(("ca:unanalyzed:", "data:unread:"))
        }
        & set(modules)
    )
    routes = [r for r in rows if r.kind == "route"]
    route_evidence: dict[uuid.UUID, list[Evidence]] = {}
    if routes:
        for ev in (
            await session.execute(
                select(Evidence).where(
                    Evidence.claim_version_id.in_([r.version_id for r in routes])
                )
            )
        ).scalars():
            route_evidence.setdefault(ev.claim_version_id, []).append(ev)
    uncovered_routes = []
    for route in routes:
        spans = route_evidence.get(route.version_id, [])
        hit = any(
            _overlaps(e, s.path or "", s.start_line, s.end_line) for s in spans for e in cited
        )
        if not hit:
            uncovered_routes.append(route.key)
    return Coverage(
        modules=Rate(sum(1 for m in modules if m in documented), len(modules)),
        endpoints=Rate(len(routes) - len(uncovered_routes), len(routes)),
        uncovered_modules=tuple(m for m in modules if m not in documented),
        unreadable_modules=tuple(unreadable),
        uncovered_endpoints=tuple(sorted(uncovered_routes)),
    )


async def report_markdown(
    session: AsyncSession,
    run_id: uuid.UUID,
    reader: SnapshotReader,
    *,
    today: dt.date | None = None,
) -> str:
    rows: list[ClaimRow] = await _rows(session, Claim.run_id == run_id)
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
    today = today or dt.datetime.now(dt.UTC).date()
    cov = await coverage(session, run_id, reader)
    acc = await accuracy(session, run_id)
    status = Counter(r.status for r in rows)
    decision = Counter(r.decision or "undecided" for r in rows)
    limit = _limit()
    out = [
        "# Review report (REV-3)",
        "",
        f"- Snapshot: `{snapshot.revision}` ({snapshot.source_kind}, {snapshot.source_ref})",
        f"- Run: `{run_id}`",
        f"- Date: {today.isoformat()}",
        f"- Claims in this run: {len(rows)} ({status['confirmed']} Confirmed, "
        f"{status['inferred']} Inferred, {status['unknown']} Unknown); "
        f"{decision['accept']} accepted, {decision['reject']} rejected, "
        f"{decision['edit']} replaced by an edit, {decision['undecided']} undecided",
        f"- Pilot size limit (REV-3.5): {limit} claims. "
        + (
            "**EXCEEDED: narrow the slice, do not shorten the review.**"
            if len(rows) > limit
            else "Within the limit."
        ),
        "",
        "## Documentation coverage (REV-3.1)",
        "",
        f"- Modules with an accepted claim: {cov.modules.show()}",
        f"- Endpoints with an accepted claim: {cov.endpoints.show()}",
        "- Modules are the first-party source files Discovery finds. Endpoints are the route "
        "claims. A module or endpoint counts once an accepted claim cites it. Everything found "
        "stays in the denominator.",
    ]
    if cov.unreadable_modules:
        out.append(
            "- Modules the parser could not read (counted as undocumented): "
            + ", ".join(f"`{m}`" for m in cov.unreadable_modules)
        )
    if cov.uncovered_modules:
        out.append(
            "- Modules without an accepted claim: "
            + ", ".join(f"`{m}`" for m in cov.uncovered_modules)
        )
    if cov.uncovered_endpoints:
        out.append(
            "- Endpoints without an accepted claim: "
            + ", ".join(f"`{k}`" for k in cov.uncovered_endpoints)
        )
    out += ["", "## Accuracy (REV-3.2 to REV-3.4)", ""]
    if acc.sample is None:
        out += [f"- {acc.verdict}"]
    else:
        s = acc.sample
        out += [
            f"- Target: {100 * _target():.0f}% of sampled claims marked correct. The interval's "
            f"lower bound must reach it.",
            f"- Sample: {acc.size} claims drawn at random (seed {s.seed}) from {s.eligible} "
            f"eligible (Confirmed or Inferred, no decision yet) on {s.drawn_at:%Y-%m-%d} by "
            f"{s.drawn_by}. Minimum {_minimum()}."
            + (" **Below the minimum.**" if s.below_minimum else ""),
            f"- Decided: {acc.decided} of {acc.size}. Marked correct (accepted): {acc.correct}.",
            f"- Accuracy: {acc.rate.show()}",
        ]
        for st, (good, total) in sorted(acc.by_status.items()):
            out.append(f"  - {st}: {Rate(good, total).show()}")
        out += [
            f"- **{acc.verdict}**",
            "- Accept counts as correct. Reject and edit do not: an edit means the claim needed "
            "changing. Unknown claims are not in the sample: they state what is not known.",
        ]
    out.append("")
    return "\n".join(out)
