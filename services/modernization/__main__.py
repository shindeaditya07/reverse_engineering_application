"""python -m services.modernization RUN_ID --out DIR

Proposes boundaries, a tech-debt map and a phased plan from the ACCEPTED claims of a run
(OUT-1.5). Claims that are not accepted appear only by key under "Unknown dependencies". Every
proposal is labelled and cites claims (OUT-1.3); nothing promises a migration is safe (OUT-1.4).
Writes modernization.md and modernization.map.json. No model is called. Reads only the claim store.
"""

import argparse
import asyncio
import datetime as dt
import sys
import uuid
from pathlib import Path

from services.db.session import make_engine, session_scope
from services.documentation import DocClaim
from services.documentation.load import load_claims
from services.modernization.plan import build_plan
from services.modernization.render import check, render


def make(
    claims: list[DocClaim], *, revision: str, run_id: uuid.UUID, today: dt.date
) -> tuple[str, str]:
    stamp = f"Snapshot `{revision}` · Run `{run_id}` · {today.isoformat()} · accepted claims only"
    markdown, mapping = render(build_plan(claims), stamp)
    problems = check(markdown, claims)
    if problems:  # a bug here, never a data problem: refuse to write
        raise AssertionError(problems[0])
    return markdown, mapping


async def run(run_id: uuid.UUID) -> tuple[str, str]:
    engine = make_engine()
    try:
        async with session_scope(engine) as session:
            claims, revision = await load_claims(session, run_id)
    finally:
        await engine.dispose()
    return make(claims, revision=revision, run_id=run_id, today=dt.datetime.now(dt.UTC).date())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=uuid.UUID)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        markdown, mapping = asyncio.run(run(args.run_id))
    except LookupError as error:
        print(error, file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "modernization.md").write_text(markdown, encoding="utf-8")
    (args.out / "modernization.map.json").write_text(mapping, encoding="utf-8")
    print(f"Wrote {args.out}/modernization.md and modernization.map.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
