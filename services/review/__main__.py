"""python -m services.review queue | show | accept | reject | edit | history | export

The review CLI (build plan, Phase 2). A reviewer works through the queue claim by claim. Every
decision names a reviewer and is recorded append-only. Nothing is accepted automatically.
Unlike the worker, this tool prints claim text: it is the reviewer's own terminal.
"""

import argparse
import asyncio
import datetime as dt
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.settings import get_settings
from services.db.models import Claim, ClaimVersion
from services.db.session import make_engine, session_scope
from services.evidence import SnapshotReader
from services.review import (
    ClaimRow,
    ReviewError,
    decide,
    export_markdown,
    history,
    list_claims,
    resolve_version_id,
    show,
)
from services.review.service import VIEWS
from services.worker.handlers import load_reader

SHORT = 8


def _row_line(row: ClaimRow) -> str:
    marks = [row.status, row.queue_reason or "", row.decision or "undecided"]
    text = " ".join(row.text.split())
    text = text if len(text) <= 70 else text[:67] + "..."
    state = " / ".join(m for m in marks if m)
    return f"{str(row.version_id)[:SHORT]}  {row.kind:<14} v{row.version}  {state}\n    {text}"


async def _reader_for(session: AsyncSession, version_id: uuid.UUID, store: Path) -> SnapshotReader:
    snapshot_id = (
        await session.execute(
            select(Claim.snapshot_id)
            .join(ClaimVersion, ClaimVersion.claim_id == Claim.id)
            .where(ClaimVersion.id == version_id)
        )
    ).scalar_one()
    _, reader = await load_reader(session, snapshot_id, store)
    return reader


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    q = sub.add_parser("queue", help="list claims to review (latest versions)")
    q.add_argument("--run", help="only this run ID")
    q.add_argument("--view", choices=VIEWS, default="queue", help="queue = REV-2.1 open items")
    q.add_argument("--limit", type=int, default=50)

    s = sub.add_parser("show", help="one claim with its evidence")
    s.add_argument("id", help="version ID or a prefix of 8+ characters")

    def reviewer(p: argparse.ArgumentParser) -> None:
        p.add_argument("--reviewer", default=os.environ.get("REVIEWER"), help="or env REVIEWER")
        p.add_argument("--reason", help="why (required for reject and edit)")

    a = sub.add_parser("accept", help="accept; each ID is its own decision")
    a.add_argument("ids", nargs="+")
    reviewer(a)
    r = sub.add_parser("reject", help="reject; each ID is its own decision")
    r.add_argument("ids", nargs="+")
    reviewer(r)
    e = sub.add_parser("edit", help="replace the wording; stored as a new Inferred version")
    e.add_argument("id")
    e.add_argument("--text", required=True)
    e.add_argument("--cite", action="append", default=[], help="PATH:START-END; replaces evidence")
    reviewer(e)

    h = sub.add_parser("history", help="decisions, newest first")
    h.add_argument("id", nargs="?", help="limit to the claim this version belongs to")
    h.add_argument("--limit", type=int, default=50)

    x = sub.add_parser("export", help="Markdown of the accepted claims of a run")
    x.add_argument("run")
    x.add_argument("--out", help="file to write; default stdout")
    return parser


async def _run(args: argparse.Namespace) -> int:
    store = Path(get_settings().snapshot_dir).resolve()
    engine = make_engine()
    try:
        async with session_scope(engine) as session:
            return await _dispatch(session, args, store)
    finally:
        await engine.dispose()


async def _dispatch(session: AsyncSession, args: argparse.Namespace, store: Path) -> int:
    if args.command == "queue":
        run = uuid.UUID(args.run) if args.run else None
        rows = await list_claims(session, run_id=run, view=args.view, limit=args.limit)
        for row in rows:
            print(_row_line(row))
        print(f"{len(rows)} shown (view: {args.view})")
        return 0
    if args.command == "show":
        vid = await resolve_version_id(session, args.id)
        try:
            reader: SnapshotReader | None = await _reader_for(session, vid, store)
        except Exception as error:
            print(
                f"warning: snapshot not readable ({type(error).__name__}); no excerpts",
                file=sys.stderr,
            )
            reader = None
        view = await show(session, vid, reader)
        r = view.row
        print(
            f"{r.version_id}\n{r.kind} `{r.key}` v{r.version}  {r.status}  "
            f"by {view.producer} ({view.producer_kind})"
        )
        print(f"queue: {r.queue_reason or '-'}   decision: {r.decision or 'none'}")
        if view.failed_checks:
            print(f"failed checks: {', '.join(view.failed_checks)}")
        print(f"\n{r.text}\n")
        for ev in view.evidence:
            print(f"evidence: {ev.ref}")
            if ev.excerpt is not None:
                print("".join(f"  | {line}\n" for line in ev.excerpt.splitlines()), end="")
            elif ev.note:
                print(f"  ({ev.note})")
        return 0
    if args.command in ("accept", "reject", "edit"):
        ids = args.ids if args.command != "edit" else [args.id]
        failures = 0
        for given in ids:
            try:
                vid = await resolve_version_id(session, given)
                reader = await _reader_for(session, vid, store)
                async with session.begin_nested():  # one refused claim never undoes the others
                    done = await decide(
                        session,
                        version_id=vid,
                        decision=args.command,
                        reviewer=args.reviewer or "",
                        reason=args.reason,
                        reader=reader,
                        new_text=getattr(args, "text", None),
                        cites=getattr(args, "cite", ()),
                    )
                extra = (
                    f" -> new version {str(done.new_version_id)[:SHORT]} stored {done.new_status}"
                    if done.new_version_id
                    else ""
                )
                print(f"{args.command}: {str(vid)[:SHORT]}{extra}")
            except ReviewError as error:
                failures += 1
                print(f"refused {given}: {error}", file=sys.stderr)
        return 1 if failures else 0
    if args.command == "history":
        scope = await resolve_version_id(session, args.id) if args.id else None
        for d in await history(session, version_id=scope, limit=args.limit):
            when, who = f"{d['decided_at']:%Y-%m-%d %H:%M}", d["reviewer"]
            print(
                f"{when}  {d['decision']:<6} {who}  {d['key']} v{d['version']}  {d['reason'] or ''}"
            )
        return 0
    text = await export_markdown(session, uuid.UUID(args.run), today=dt.datetime.now(dt.UTC).date())
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except (ReviewError, LookupError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
