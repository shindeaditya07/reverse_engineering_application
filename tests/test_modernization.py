"""Modernization agent: proposals from accepted claims only, each citing claims, none promising."""

import dataclasses
import datetime as dt
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from services import codeanalysis, data, discovery
from services.businessrule.run import pin_fixture
from services.documentation import DocClaim
from services.documentation.load import load_claims
from services.evidence import SnapshotReader
from services.modernization import Item, build_plan, check, render
from services.modernization.__main__ import main, make
from services.modernization.plan import CROSS, PHASES, RULES
from services.modernization.render import NOT_A_PROMISE, PROMISES
from tests.test_review import accept, put, session, world  # noqa: F401  (fixtures)

RUN = uuid.UUID(int=3)
TODAY = dt.date(2026, 11, 9)


@pytest.fixture(scope="module")
def claims(tmp_path_factory: pytest.TempPathFactory) -> list[DocClaim]:
    pinned = pin_fixture(tmp_path_factory.mktemp("pin"))
    reader = SnapshotReader.from_pinned(pinned)
    paths = [f.path for f in pinned.tree.files]
    found = []
    for agent in (discovery.discover, codeanalysis.analyze, data.analyze):
        for f in agent(reader, paths).findings:
            found.append(DocClaim(f.claim_id, f.kind, f.status, f.text, f.status != "unknown"))
    return found


def doc(claims: list[DocClaim]) -> str:
    return make(claims, revision="abc123", run_id=RUN, today=TODAY)[0]


def test_every_proposal_cites_accepted_claims_verbatim(claims: list[DocClaim]) -> None:
    plan = build_plan(claims)
    assert len(plan.items) > 15 and all(i.cites for i in plan.items)
    assert check(doc(claims), claims) == []


def test_a_proposal_without_a_claim_cannot_be_built() -> None:
    with pytest.raises(ValueError):
        Item("P-01", 1, "Do something.", ())


def test_only_accepted_claims_are_used_and_the_rest_are_named_by_key(
    claims: list[DocClaim],
) -> None:
    some = [dataclasses.replace(c, accepted=c.kind == "route") for c in claims]
    text = doc(some)
    plan = build_plan(some)
    assert plan.accepted == sum(c.kind == "route" for c in some) and plan.total == len(some)
    assert {i.cites[0].key.split(":")[0] for i in plan.items} <= {"ca"}
    for c in some:
        if not c.accepted:
            assert " ".join(c.text.split()) not in text  # never quoted
    assert "`data:table:db/schema.sql:orders`" in text  # named in Unknown dependencies
    assert "## Unknown dependencies" in text and "None: every claim" not in text


def test_nothing_accepted_gives_an_empty_plan_that_says_so(claims: list[DocClaim]) -> None:
    none = [dataclasses.replace(c, accepted=False) for c in claims]
    text = doc(none)
    assert "0 of " in text and "No accepted claim gives a basis" in text
    assert "No boundary is proposed" in text and "[proposal]" not in text


def test_unknown_claims_are_never_a_basis_even_if_marked_accepted() -> None:
    odd = DocClaim("ca:dead:x.js:f", "dead_code", "unknown", "x.js was not read.", True)
    assert build_plan([odd]).items == ()


def test_candidate_boundaries_and_the_cross_boundary_write(claims: list[DocClaim]) -> None:
    plan = build_plan(claims)
    names = {b.name: b for b in plan.boundaries}
    assert {"orders", "customers", "products", "reports"} <= set(names)
    assert "services/orders_service.js" in names["orders"].files
    assert [t.key for t in names["orders"].tables] == ["data:table:db/schema.sql:orders"]
    crossing = [i for i in plan.items if i.action == CROSS]
    assert crossing and any(
        "data:sql:services/orders_service.js" in i.cites[0].key
        and i.cites[1].key == "data:table:db/schema.sql:products"
        for i in crossing
    )


def test_every_item_is_labelled_and_phased(claims: list[DocClaim]) -> None:
    text = doc(claims)
    assert "**PROPOSAL, not a finding.**" in text and NOT_A_PROMISE in text
    assert text.count("[proposal]") == len(build_plan(claims).items)
    assert {i.phase for i in build_plan(claims).items} <= set(PHASES)
    assert "Snapshot `abc123`" in text and str(RUN) in text and "2026-11-09" in text


def test_none_of_our_wording_promises_safety() -> None:
    fixed = [a for *_, a in RULES] + [CROSS] + list(PHASES.values())
    for sentence in fixed:
        assert not PROMISES.search(sentence), sentence
    assert "will be safe" in NOT_A_PROMISE  # the one place the word appears, in a negation


def test_check_catches_every_way_to_break_the_rules(claims: list[DocClaim]) -> None:
    text = doc(claims)
    first = next(c for c in claims if c.kind == "route" and c.accepted)
    assert check(text.replace(first.text, first.text + " Safely."), claims)
    assert check(text.replace(first.key, "ca:route:made-up", 1), claims)
    assert check(text.replace("**Confirmed**", "**Inferred**", 1), claims)
    assert check(text + "\n- **P-99** [proposal] Rewrite everything.\n", claims)
    assert check(
        text.replace("Keep this", "This is safe") + "\n- **P-98** [proposal] A safe move.\n", claims
    )
    rejected = [dataclasses.replace(c, accepted=False) if c.key == first.key else c for c in claims]
    assert check(text, rejected)  # a claim that is no longer accepted may not be cited
    leaked = DocClaim("x:1", "route", "inferred", "app.js line 1 registers GET /x.", False)
    assert check(text + "\n" + leaked.text, [*claims, leaked])


def test_an_edited_route_claim_is_skipped_not_guessed() -> None:
    odd = DocClaim("ca:route:a.js:1", "route", "inferred", "A reviewer wrote this by hand.", True)
    plan = build_plan([odd])
    assert plan.boundaries == () and plan.items == ()


def test_hostile_route_names_do_not_become_boundaries() -> None:
    bad = DocClaim(
        "ca:route:a.js:1", "route", "confirmed", "a.js line 1 registers GET /api/x\ny.", True
    )
    assert build_plan([bad]).boundaries == ()


@pytest.mark.requires_db
async def test_loader_to_plan_uses_the_review_decision(
    session: AsyncSession,  # noqa: F811
    world: Any,  # noqa: F811
) -> None:
    kw: dict[str, Any] = {"kind": "dead_code", "status": "inferred", "producer_kind": "model"}
    seen = await put(session, world, "ca:dead:a.js:f", text="f is exported from a.js but nothing calls it.", **kw)  # fmt: skip
    await put(session, world, "ca:dead:a.js:g", text="g is exported from a.js but nothing calls it.", **kw)  # fmt: skip
    await accept(session, world, seen)
    got, revision = await load_claims(session, world[2])
    text = make(got, revision=revision, run_id=world[2], today=TODAY)[0]
    assert "f is exported" in text and "g is exported" not in text and "`ca:dead:a.js:g`" in text


def test_cli_needs_an_output_folder() -> None:
    with pytest.raises(SystemExit):
        main([str(RUN)])


def test_render_returns_a_map_of_proposals_to_claim_keys(claims: list[DocClaim]) -> None:
    _, mapping = render(build_plan(claims), "stamp")
    assert '"P-01"' in mapping and '"boundary:orders"' in mapping


def _route(line: int, *routes: str) -> DocClaim:
    return DocClaim(
        f"ca:route:routes/r.js:{line}",
        "route",
        "confirmed",
        f"routes/r.js line {line} registers {', '.join(routes)}.",
        True,
    )


def test_routes_without_an_api_prefix_are_grouped_by_their_first_name() -> None:
    plan = build_plan(
        [
            _route(1, "GET /admin/products/:page?"),
            _route(2, "POST /admin/product/insert"),
            _route(3, "GET /product/:id"),
            _route(4, "GET /admin/customers"),
            _route(5, "POST /customer/login_action"),
        ]
    )
    names = {b.name: len(b.routes) for b in plan.boundaries}
    assert names == {"customer": 2, "product": 3}  # admin and public routes join; plural joins


def test_a_name_on_one_route_with_no_table_is_not_a_boundary() -> None:
    plan = build_plan([_route(1, "GET /sitemap.xml"), _route(2, "GET /lang/:locale")])
    assert plan.boundaries == ()


def _route_in(file: str, line: int, *routes: str) -> DocClaim:
    return DocClaim(
        f"ca:route:{file}:{line}",
        "route",
        "inferred",
        f"{file} line {line} registers {', '.join(routes)}.",
        True,
    )


def test_routes_with_hyphenated_paths_are_grouped_by_their_folder() -> None:
    plan = build_plan(
        [
            _route_in("routes/user/signIn.js", 3, "GET /sign-in", "POST /sign-in"),
            _route_in("routes/user/logOut.js", 2, "GET /log-out"),
            _route_in("routes/home.js", 1, "GET /"),
            DocClaim(
                "data:table:equantom.sql:users",
                "table",
                "confirmed",
                "equantom.sql defines table users with columns id, email (no primary key).",
                True,
            ),
        ]
    )
    (b,) = plan.boundaries
    assert b.name == "user" and len(b.routes) == 2 and len(b.tables) == 1  # users table attaches
    assert plan.shared_tables == ()


def test_a_table_without_a_primary_key_is_still_listed() -> None:
    plan = build_plan(
        [
            DocClaim(
                "data:table:s.sql:orders",
                "table",
                "confirmed",
                "s.sql defines table orders with columns id, total (no primary key).",
                True,
            )
        ]
    )
    assert len(plan.shared_tables) == 1
