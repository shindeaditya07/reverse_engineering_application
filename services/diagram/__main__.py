"""python -m services.diagram RUN_ID [--accepted-only] [--out DIR]

Draws the stored claims of a run as Mermaid (OUT-1.1): tables and relations, modules and what
they read, write or call, and the step order of async functions and callback chains. Writes
diagrams.md (stamped with snapshot, run and date) and diagrams.map.json (element -> claim keys)
under DIR, or prints the markdown. Reads only the claim store.
"""

import argparse
import asyncio
import datetime as dt
import sys
import uuid
from pathlib import Path

from services.db.session import make_engine, session_scope
from services.diagram.load import build, document, load_claims


async def run(run_id: uuid.UUID, accepted_only: bool) -> tuple[str, str]:
    engine = make_engine()
    try:
        async with session_scope(engine) as session:
            claims, total, revision = await load_claims(
                session, run_id, accepted_only=accepted_only
            )
    finally:
        await engine.dispose()
    diagrams, omitted = build(claims)
    return document(
        diagrams,
        omitted,
        revision=revision,
        run_id=run_id,
        total=total,
        accepted_only=accepted_only,
        today=dt.datetime.now(dt.UTC).date(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=uuid.UUID)
    parser.add_argument("--accepted-only", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        markdown, mapping = asyncio.run(run(args.run_id, args.accepted_only))
    except LookupError as error:
        print(error, file=sys.stderr)
        return 1
    if args.out is None:
        print(markdown)
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "diagrams.md").write_text(markdown, encoding="utf-8")
    (args.out / "diagrams.map.json").write_text(mapping, encoding="utf-8")
    print(f"Wrote {args.out}/diagrams.md and diagrams.map.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
