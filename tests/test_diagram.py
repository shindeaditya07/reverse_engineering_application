"""Diagram agent: Mermaid from claims, every element mapped to a claim (OUT-1.1)."""

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from services import codeanalysis, data, discovery
from services.businessrule.run import pin_fixture
from services.diagram import DiagramClaim, extract, render
from services.diagram.load import build, document, load_claims
from services.diagram.model import Builder, label
from services.evidence import SnapshotReader
from tests.test_review import accept, put, session, world  # noqa: F401  (fixtures)

PREFIXES = (
    "data:table:", "data:relation:", "data:sql:", "ca:route:", "disc:http:", "disc:socket:",
    "disc:timer:", "ca:async-flow:", "ca:callback-chain:", "ca:promise-chain:",
)  # fmt: skip


@pytest.fixture(scope="module")
def claims(tmp_path_factory: pytest.TempPathFactory) -> list[DiagramClaim]:
    pinned = pin_fixture(tmp_path_factory.mktemp("pin"))
    reader = SnapshotReader.from_pinned(pinned)
    paths = [f.path for f in pinned.tree.files]
    found = []
    for agent in (discovery.discover, codeanalysis.analyze, data.analyze):
        for f in agent(reader, paths).findings:
            found.append(DiagramClaim(f.claim_id, f.kind, f.status, f.text))
    return found


def test_every_fixture_claim_of_a_drawn_kind_is_understood(claims: list[DiagramClaim]) -> None:
    """Contract with the analyzers: if a claim template changes, this fails."""
    mine = [c for c in claims if c.key.startswith(PREFIXES) and c.status != "unknown"]
    found = extract(claims)
    assert found.omitted == ()
    drawn = (
        len(found.tables) + len(found.relations) + len(found.access) + len(found.routes)
        + len(found.outbound) + len(found.flows)
    )  # fmt: skip
    assert drawn == len(mine) > 20


def test_the_fixture_gives_er_architecture_and_workflows(claims: list[DiagramClaim]) -> None:
    names = [d.name for d in render(extract(claims))]
    assert names[:2] == ["er", "architecture"]
    assert all(n.startswith("workflow:") for n in names[2:]) and len(names) == 6


def test_every_element_maps_to_claims_that_exist(claims: list[DiagramClaim]) -> None:
    keys = {c.key for c in claims}
    for d in render(extract(claims)):
        assert d.mapping
        for element, mapped in d.mapping.items():
            assert mapped and set(mapped) <= keys, (d.name, element)


def test_the_mapping_covers_every_node_and_edge_in_the_text(claims: list[DiagramClaim]) -> None:
    arch = next(d for d in render(extract(claims)) if d.name == "architecture")
    node_ids = set(re.findall(r"^  ([a-z]_\w+)[\[(]", arch.mermaid, re.M))
    edges = re.findall(r"^  ([a-z]_\w+) -[.-]*>(?:\|[^|]*\|)? ([a-z]_\w+)", arch.mermaid, re.M)
    assert node_ids and edges
    assert node_ids <= set(arch.mapping)
    mapped_edges = {tuple(k.split("#")[0].split("->")) for k in arch.mapping if "->" in k}
    assert set(edges) <= mapped_edges


def test_an_element_without_a_claim_cannot_be_built() -> None:
    b = Builder()
    with pytest.raises(ValueError, match="OUT-1.1"):
        b.node("n", "  n", [])
    with pytest.raises(ValueError, match="OUT-1.1"):
        b.edge("a", "b", "  a --> b", [])


def test_unknown_claims_are_never_drawn() -> None:
    sql = "x.js line 3 reads orders.id from orders."
    found = extract([DiagramClaim("data:sql:x.js:3", "sql_read", "unknown", sql)])
    assert found.access == () and found.omitted == ()


def test_inferred_is_dashed_and_confirmed_is_solid() -> None:
    table = "db.sql defines table {t} with columns id (primary key id)."
    rel = "{a}.{c} looks like a reference to {b}.id by its name, but no foreign key is declared."
    claims = [
        DiagramClaim("data:table:db.sql:a", "table", "confirmed", table.format(t="a")),
        DiagramClaim("data:table:db.sql:b", "table", "confirmed", table.format(t="b")),
        DiagramClaim("data:relation:db.sql:a.b_id", "relation", "inferred", rel.format(a="a", c="b_id", b="b")),
        DiagramClaim("data:sql:x.js:3", "sql_read", "confirmed", "x.js line 3 reads a.id from a."),
        DiagramClaim("data:sql:y.js:4", "sql_read", "inferred", "y.js line 4 reads b.id from b."),
    ]  # fmt: skip
    er, arch = render(extract(claims))
    assert "}o..||" in er.mermaid and "guessed" in er.mermaid
    assert "f_x_js -->|" in arch.mermaid and "f_y_js -.->|" in arch.mermaid
    assert "(inferred)" in arch.mermaid


def test_hostile_names_cannot_inject_mermaid() -> None:
    evil = 'a"];click.js'
    text = f'{evil} line 3 registers GET /x"]--> y;click.'
    claims = [DiagramClaim(f"ca:route:{evil}:3", "route", "confirmed", text)]
    (arch,) = [d for d in render(extract(claims)) if d.name == "architecture"]
    body = "\n".join(arch.mermaid.splitlines()[1:])
    assert body.count('"') == 2 and ";" not in body and "]-->" not in body


def test_label_is_safe_and_bounded() -> None:
    out = label('x"<script>\nalert(1)|`]')
    assert re.fullmatch(r"[A-Za-z0-9 _./:,()+\-*=?$@#]*", out) and "<" not in out
    assert len(label("a" * 500)) == 60


def test_edited_claims_are_listed_not_guessed() -> None:
    claims = [DiagramClaim("data:table:db.sql:t", "table", "inferred", "a reviewer's own words")]
    found = extract(claims)
    assert found.tables == () and found.omitted[0][0] == "data:table:db.sql:t"
    assert "not in the expected form" in found.omitted[0][1]


def test_document_is_stamped_and_says_how_much_is_drawn(claims: list[DiagramClaim]) -> None:
    diagrams, omitted = build(claims)
    run_id = uuid.uuid4()
    md, mapping = document(
        diagrams, omitted, revision="abc123", run_id=run_id, total=72,
        accepted_only=False, today=dt.date(2026, 11, 9),
    )  # fmt: skip
    assert "`abc123`" in md and str(run_id) in md and "2026-11-09" in md
    used = len({k for d in diagrams for v in d.mapping.values() for k in v})
    assert f"{used} of 72 claims" in md and "Unknown is\n" not in md and "never drawn" in md
    assert md.count("```mermaid") == len(diagrams)
    assert set(json.loads(mapping)) == {d.name for d in diagrams}


def test_output_parses_with_the_real_mermaid_parser(claims: list[DiagramClaim]) -> None:
    """Runs only where Mermaid is installed (see scripts/check_mermaid.mjs); CI does not."""
    folder = os.environ.get("MERMAID_DIR")
    if not folder or not shutil.which("node"):
        pytest.skip("set MERMAID_DIR to a folder with mermaid and jsdom installed")
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for i, d in enumerate(render(extract(claims))):
            path = Path(tmp) / f"{i}.mmd"
            path.write_text(d.mermaid + "\n", encoding="utf-8")
            files.append(str(path))
        script = Path(__file__).resolve().parents[1] / "scripts" / "check_mermaid.mjs"
        shutil.copy(script, Path(folder) / "check_mermaid.mjs")
        done = subprocess.run(
            ["node", "check_mermaid.mjs", *files], cwd=folder, capture_output=True, text=True
        )
    assert done.returncode == 0, done.stdout + done.stderr


# ---- the loader, over the real claim store -----------------------------------------------------

TABLE = "db/schema.sql defines table customers with columns id (primary key id)."


@pytest.mark.requires_db
async def test_loader_skips_unknown_and_withheld_and_honours_accepted_only(
    session: AsyncSession,  # noqa: F811
    world: Any,  # noqa: F811
) -> None:
    run_id = world[2]
    kw: dict[str, Any] = {"kind": "table"}
    seen = await put(session, world, "data:table:db/schema.sql:customers", text=TABLE, **kw)
    await put(session, world, "data:table:db/schema.sql:ghost", text=TABLE, evidence=False,
              status="inferred", producer_kind="model", **kw)  # fmt: skip
    await accept(session, world, seen)
    await put(session, world, "data:table:db/schema.sql:orders",
              text="db/schema.sql defines table orders with columns id.", **kw)  # fmt: skip
    every, total, revision = await load_claims(session, run_id, accepted_only=False)
    assert total == 3 and revision == world[0].revision
    assert {c.key.rsplit(":", 1)[1] for c in every} == {"customers", "orders"}  # ghost: Unknown
    only, _, _ = await load_claims(session, run_id, accepted_only=True)
    assert [c.key.rsplit(":", 1)[1] for c in only] == ["customers"]
    diagrams, omitted = build(only)
    assert [d.name for d in diagrams] == ["er"] and omitted == ()


@pytest.mark.requires_db
async def test_loader_refuses_a_run_with_no_claims(session: AsyncSession) -> None:  # noqa: F811
    with pytest.raises(LookupError):
        await load_claims(session, uuid.uuid4(), accepted_only=False)


def test_a_flow_in_an_anonymous_function_is_drawn_not_omitted() -> None:
    text = (
        "an anonymous function in routes/a.js line 5 is async and awaits 2 steps, "
        "in source order: db.a.find(), render()."
    )
    found = extract([DiagramClaim("ca:async-flow:routes/a.js:5", "flow", "confirmed", text)])
    assert found.omitted == ()
    (flow,) = found.flows
    assert flow.name == "an anonymous function" and flow.steps == ("db.a.find()", "render()")
