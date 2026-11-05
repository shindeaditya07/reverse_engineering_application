import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from services.db.session import make_engine

pytestmark = pytest.mark.requires_db

TABLES = {
    "snapshots",
    "snapshot_files",
    "claims",
    "claim_versions",
    "evidence",
    "verification_results",
    "review_items",
    "review_decisions",
    "artifacts",
    "audit_log",
    "jobs",
    "model_calls",
}


async def expect_error(
    conn: AsyncConnection, sql: str, params: dict[str, object] | None = None
) -> str:
    """Run a statement that must fail inside a savepoint, and return the database's message."""
    with pytest.raises(DBAPIError) as caught:
        async with conn.begin_nested():
            await conn.execute(text(sql), params or {})
    return str(caught.value)


async def make_claim(conn: AsyncConnection) -> tuple[uuid.UUID, uuid.UUID]:
    snapshot = uuid.uuid4()
    claim = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO snapshots (id, source_kind, source_ref, revision) VALUES (:s, 'github', :r, 'abc')"
        ),
        {"s": snapshot, "r": f"https://example.test/{snapshot}"},
    )
    await conn.execute(
        text("INSERT INTO claims (id, snapshot_id, run_id, kind) VALUES (:c, :s, :r, 'route')"),
        {"c": claim, "s": snapshot, "r": uuid.uuid4()},
    )
    return snapshot, claim


async def add_version(
    conn: AsyncConnection, claim: uuid.UUID, version: int, status: str, producer_kind: str
) -> uuid.UUID:
    version_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO claim_versions (id, claim_id, version, text, status, producer, producer_kind) "
            "VALUES (:i, :c, :v, 't', :s, 'test', :k)"
        ),
        {"i": version_id, "c": claim, "v": version, "s": status, "k": producer_kind},
    )
    return version_id


async def add_evidence(
    conn: AsyncConnection, snapshot: uuid.UUID, version_id: uuid.UUID, start: int, end: int
) -> None:
    await conn.execute(
        text(
            "INSERT INTO evidence (claim_version_id, snapshot_id, kind, path, start_line, end_line, content_hash) "
            "VALUES (:v, :s, 'file_range', 'app.js', :a, :b, 'h')"
        ),
        {"v": version_id, "s": snapshot, "a": start, "b": end},
    )


async def test_all_tables_exist(connection: AsyncConnection) -> None:
    rows = await connection.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    )
    assert TABLES <= {row[0] for row in rows}


async def test_no_accepted_column_exists(connection: AsyncConnection) -> None:
    """REV-1.1: acceptance exists only as a review decision, never as a flag."""
    rows = await connection.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name ~* 'accept'"
        )
    )
    assert list(rows) == []


async def test_model_alone_cannot_produce_confirmed(connection: AsyncConnection) -> None:
    _, claim = await make_claim(connection)
    message = await expect_error(
        connection,
        "INSERT INTO claim_versions (claim_id, version, text, status, producer, producer_kind) "
        "VALUES (:c, 1, 't', 'confirmed', 'm', 'model')",
        {"c": claim},
    )
    assert "confirmed_not_model_only" in message


async def test_confirmed_by_deterministic_analysis_with_evidence_is_accepted(
    connection: AsyncConnection,
) -> None:
    snapshot, claim = await make_claim(connection)
    version = await add_version(connection, claim, 1, "confirmed", "deterministic")
    await add_evidence(connection, snapshot, version, 1, 5)
    await connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.parametrize("status", ["confirmed", "inferred"])
async def test_confirmed_or_inferred_without_evidence_fails_at_commit(
    connection: AsyncConnection, status: str
) -> None:
    _, claim = await make_claim(connection)
    kind = "deterministic" if status == "confirmed" else "model"
    await add_version(connection, claim, 1, status, kind)
    message = await expect_error(connection, "SET CONSTRAINTS ALL IMMEDIATE")
    assert "has no evidence" in message


async def test_unknown_claim_needs_no_evidence(connection: AsyncConnection) -> None:
    _, claim = await make_claim(connection)
    await add_version(connection, claim, 1, "unknown", "model")
    await connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


async def test_evidence_span_limit_matches_the_constants_file(connection: AsyncConnection) -> None:
    limit = yaml.safe_load(Path("rules_constants.yaml").read_text())["EVD-1.4"]["max_excerpt_lines"]
    snapshot, claim = await make_claim(connection)
    version = await add_version(connection, claim, 1, "unknown", "model")
    await add_evidence(connection, snapshot, version, 1, limit)  # exactly at the limit: accepted
    with pytest.raises(DBAPIError) as caught:
        async with connection.begin_nested():
            await add_evidence(connection, snapshot, version, 1, limit + 1)
    assert "file_range_valid" in str(caught.value)


@pytest.mark.parametrize(
    ("start", "end"), [(0, 3), (5, 4)], ids=["lines_start_at_one", "end_not_before_start"]
)
async def test_invalid_line_ranges_are_rejected(
    connection: AsyncConnection, start: int, end: int
) -> None:
    snapshot, claim = await make_claim(connection)
    version = await add_version(connection, claim, 1, "unknown", "model")
    with pytest.raises(DBAPIError):
        async with connection.begin_nested():
            await add_evidence(connection, snapshot, version, start, end)


async def insert_byte_evidence(
    conn: AsyncConnection,
    snapshot: uuid.UUID,
    version: uuid.UUID,
    columns: str,
    values: str,
) -> None:
    await conn.execute(
        text(
            f"INSERT INTO evidence (claim_version_id, snapshot_id, kind, path, content_hash, {columns}) "
            f"VALUES (:v, :s, 'file_range', 'lib/x.js', 'h', {values})"
        ),
        {"v": version, "s": snapshot},
    )


async def test_byte_range_evidence_is_accepted(connection: AsyncConnection) -> None:
    """EVD-1.5: an undecodable file is cited by byte range."""
    snapshot, claim = await make_claim(connection)
    version = await add_version(connection, claim, 1, "unknown", "model")
    await insert_byte_evidence(connection, snapshot, version, "start_byte, end_byte", "73, 74")


@pytest.mark.parametrize(
    ("columns", "values"),
    [
        ("start_byte, end_byte", "5, 5"),
        ("start_byte, end_byte", "-1, 4"),
        ("start_byte", "5"),
        ("start_line, end_line, start_byte, end_byte", "1, 2, 3, 4"),
        ("start_byte, end_byte, start_line", "3, 4, 1"),
        ("start_line", "3"),
        ("end_byte", "3"),
        ("start_line, end_line", "NULL, NULL"),
    ],
    ids=[
        "empty",
        "negative",
        "no_end",
        "lines_and_bytes",
        "bytes_and_one_line",
        "half_a_line_range",
        "end_byte_only",
        "no_range_at_all",
    ],
)
async def test_invalid_byte_ranges_are_rejected(
    connection: AsyncConnection, columns: str, values: str
) -> None:
    snapshot, claim = await make_claim(connection)
    version = await add_version(connection, claim, 1, "unknown", "model")
    with pytest.raises(DBAPIError) as caught:
        async with connection.begin_nested():
            await insert_byte_evidence(connection, snapshot, version, columns, values)
    assert "file_range_valid" in str(caught.value)


async def test_claim_versions_are_append_only(connection: AsyncConnection) -> None:
    _, claim = await make_claim(connection)
    version = await add_version(connection, claim, 1, "unknown", "model")
    update = await expect_error(
        connection, "UPDATE claim_versions SET text = 'changed' WHERE id = :i", {"i": version}
    )
    assert "append-only" in update
    delete = await expect_error(
        connection, "DELETE FROM claim_versions WHERE id = :i", {"i": version}
    )
    assert "append-only" in delete


async def test_review_decisions_and_audit_log_are_append_only(connection: AsyncConnection) -> None:
    _, claim = await make_claim(connection)
    version = await add_version(connection, claim, 1, "unknown", "model")
    await connection.execute(
        text(
            "INSERT INTO review_decisions (claim_version_id, decision, reviewer) VALUES (:v, 'reject', 'aditya')"
        ),
        {"v": version},
    )
    await connection.execute(
        text(
            "INSERT INTO audit_log (actor, action, subject_type, subject_id) VALUES ('t', 'a', 'claim', 'x')"
        )
    )
    for table in ("review_decisions", "audit_log"):
        for sql in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}", f"TRUNCATE {table}"):
            assert "append-only" in await expect_error(connection, sql), sql


async def test_a_decision_needs_a_named_reviewer(connection: AsyncConnection) -> None:
    _, claim = await make_claim(connection)
    version = await add_version(connection, claim, 1, "unknown", "model")
    message = await expect_error(
        connection,
        "INSERT INTO review_decisions (claim_version_id, decision, reviewer) VALUES (:v, 'accept', '')",
        {"v": version},
    )
    assert "reviewer_present" in message


async def test_jobs_are_idempotent_per_run_type_and_input(connection: AsyncConnection) -> None:
    run = uuid.uuid4()
    insert = "INSERT INTO jobs (run_id, job_type, input_hash) VALUES (:r, 'discovery', 'h')"
    await connection.execute(text(insert), {"r": run})
    message = await expect_error(connection, insert, {"r": run})
    assert "uq_job_identity" in message


def test_engine_has_the_resilience_settings() -> None:
    engine = make_engine("postgresql+asyncpg://u:p@localhost:1/none")
    assert engine.pool._pre_ping is True  # AGENTS.md section 4
    assert engine.pool._recycle == 1800
