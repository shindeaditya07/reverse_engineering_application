"""Documentation agent: documents assembled from claims, every statement a stored claim."""

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from services import codeanalysis, data, discovery
from services.businessrule.run import pin_fixture
from services.documentation import DocClaim, assemble, check
from services.documentation.load import build, load_claims
from services.evidence import SnapshotReader
from tests.test_review import accept, put, session, world  # noqa: F401  (fixtures)

TODAY = dt.date(2026, 11, 9)
RUN = uuid.UUID(int=7)


@pytest.fixture(scope="module")
def claims(tmp_path_factory: pytest.TempPathFactory) -> list[DocClaim]:
    pinned = pin_fixture(tmp_path_factory.mktemp("pin"))
    reader = SnapshotReader.from_pinned(pinned)
    paths = [f.path for f in pinned.tree.files]
    found = []
    for agent in (discovery.discover, codeanalysis.analyze, data.analyze):
        for f in agent(reader, paths).findings:
            found.append(DocClaim(f.claim_id, f.kind, f.status, f.text))
    return found


def files(claims: list[DocClaim], accepted_only: bool = False) -> dict[str, str]:
    return build(claims, revision="abc123", run_id=RUN, accepted_only=accepted_only, today=TODAY)


def test_every_statement_is_a_stored_claim_verbatim(claims: list[DocClaim]) -> None:
    out = files(claims)
    assert len(out) > 5
    for name, text in out.items():
        if name.endswith(".md") and name != "index.md":
            assert check(text, claims) == [], name


def test_check_rejects_a_sentence_that_is_not_a_claim(claims: list[DocClaim]) -> None:
    text = files(claims)["api-reference.md"]
    assert check(text + "- The API is fast.\n", claims)
    first = next(c for c in claims if c.kind == "route")
    assert check(text.replace(first.text, first.text + " Safely."), claims)
    assert check(text.replace("**Confirmed**", "**Inferred**", 1), claims)
    assert check(text.replace(first.key, "ca:route:made-up", 1), claims)


def test_documents_are_stamped_and_say_how_much_is_covered(claims: list[DocClaim]) -> None:
    out = files(claims)
    for name, text in out.items():
        if name.endswith(".md") and name != "index.md":
            assert "Snapshot `abc123`" in text and str(RUN) in text and "2026-11-09" in text
    index = out["index.md"]
    assert "Snapshot: `abc123`" in index and "2026-11-09" in index
    assert f"of {len(claims)} claims in this run appear" in index
    assert "Nothing was written by a model" in index


def test_claims_land_in_the_document_for_their_kind(claims: list[DocClaim]) -> None:
    out = files(claims)
    assert "GET /api/orders" in out["api-reference.md"]
    assert "defines table customers" in out["data-reference.md"]
    assert "defines table customers" in out["glossary.md"]
    assert "outbound HTTP call" in out["runbook.md"]
    assert "Column write sources" in out["data-reference.md"]


def test_unknown_claims_appear_only_as_open_questions(claims: list[DocClaim]) -> None:
    unknown = [c for c in claims if c.status == "unknown"]
    assert unknown
    out = files(claims)
    for c in unknown:
        homes = [n for n, t in out.items() if n.endswith(".md") and f"`{c.key}`" in t]
        assert homes == ["open-questions.md"], c.key


def test_queued_claims_are_listed_as_open_questions() -> None:
    c = DocClaim("br:x:1:1", "rule", "inferred", "Orders over 50 items are rejected.",
                 reason="model-produced")  # fmt: skip
    out = files([c])
    assert "Orders over 50 items" in out["business-rules.md"]
    assert "Orders over 50 items" in out["open-questions.md"]


def test_accepted_only_drops_undecided_claims() -> None:
    a = DocClaim("ca:route:a.js:1", "route", "confirmed", "a.js line 1 registers GET /a.", True)
    b = DocClaim("ca:route:b.js:1", "route", "confirmed", "b.js line 1 registers GET /b.")
    text = files([a, b], accepted_only=True)["api-reference.md"]
    assert "GET /a" in text and "GET /b" not in text
    assert "accepted claims only" in text


def test_kinds_with_no_document_are_counted_not_dropped() -> None:
    c = DocClaim("x:1", "mystery", "inferred", "Something odd.")
    docs, unplaced = assemble([c], stamp="s", accepted_only=False)
    assert docs == [] and unplaced == {"mystery": 1}
    assert "mystery: 1" in files([c])["index.md"]


def test_the_map_lists_the_claims_behind_each_document(claims: list[DocClaim]) -> None:
    mapping = json.loads(files(claims)["map.json"])
    keys = {c.key for c in claims}
    assert mapping["api-reference"] and all(k in keys for ks in mapping.values() for k in ks)


def test_model_drafted_rules_are_documented_as_inferred() -> None:
    pinned_claims = [
        DocClaim("br:a.js:3:1", "rule", "inferred", "Total is zero when the cart is empty."),
    ]
    text = files(pinned_claims)["business-rules.md"]
    assert "**Inferred** Total is zero" in text and "need a human check" in text


def test_businessrule_kinds_have_a_home() -> None:
    from services.documentation.assemble import PLACE

    assert {"rule", "validation"} <= set(PLACE)


@pytest.mark.requires_db
async def test_loader_reads_latest_claims_and_skips_withheld_text(
    session: AsyncSession,  # noqa: F811
    world: Any,  # noqa: F811
) -> None:
    kw: dict[str, Any] = {"kind": "table"}
    seen = await put(session, world, "data:table:db/schema.sql:customers",
                     text="db/schema.sql defines table customers with columns id.", **kw)  # fmt: skip
    await accept(session, world, seen)
    await put(session, world, "data:table:db/schema.sql:orders",
              text="db/schema.sql defines table orders with columns id.", **kw)  # fmt: skip
    got, revision = await load_claims(session, world[2])
    assert revision == world[0].revision
    assert {c.key.rsplit(":", 1)[1]: c.accepted for c in got} == {
        "customers": True,
        "orders": False,
    }
    out = build(got, revision=revision, run_id=world[2], accepted_only=True, today=TODAY)
    assert "customers" in out["glossary.md"] and "orders" not in out["glossary.md"]


@pytest.mark.requires_db
async def test_loader_refuses_a_run_with_no_claims(session: AsyncSession) -> None:  # noqa: F811
    with pytest.raises(LookupError):
        await load_claims(session, uuid.uuid4())


def test_cli_refuses_without_out_dir(tmp_path: Path) -> None:
    from services.documentation.__main__ import main

    with pytest.raises(SystemExit):
        main([str(RUN)])
