"""python -m services.documentation RUN_ID [--accepted-only] --out DIR

Assembles documents from the stored claims of a run: API reference, data reference, business
rules, runbook facts, glossary and open questions, plus an index and a claim map. Every statement
is a stored claim copied verbatim (CLM-1.6); no model is called. Reads only the claim store.
"""

import argparse
import asyncio
import datetime as dt
import sys
import uuid
from pathlib import Path

from services.db.session import make_engine, session_scope
from services.documentation.load import build, load_claims


async def run(run_id: uuid.UUID, accepted_only: bool) -> dict[str, str]:
    engine = make_engine()
    try:
        async with session_scope(engine) as session:
            claims, revision = await load_claims(session, run_id)
    finally:
        await engine.dispose()
    return build(
        claims,
        revision=revision,
        run_id=run_id,
        accepted_only=accepted_only,
        today=dt.datetime.now(dt.UTC).date(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=uuid.UUID)
    parser.add_argument("--accepted-only", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        files = asyncio.run(run(args.run_id, args.accepted_only))
    except LookupError as error:
        print(error, file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (args.out / name).write_text(content, encoding="utf-8")
    print(f"Wrote {len(files)} files to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
