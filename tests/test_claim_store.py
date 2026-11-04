"""The claim store's invariants are enforced by the database, not only by application code."""

import hashlib
import uuid
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, exc, insert, inspect, text

from services.api.db import tables as t
from tests.conftest import _alembic_config

SNAP = "a" * 64


def snapshot(conn: Any, snapshot_id: str = SNAP) -> None:
    conn.execute(
        insert(t.snapshots).values(
            snapshot_id=snapshot_id,
            source_kind="archive",
            repo_name="shopledger",
            platform_version="0.1.0",
            created_by="test",
            manifest={},
        )
    )


def claim(conn: Any, **overrides: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "claim_id": uuid.uuid4(),
        "snapshot_id": SNAP,
        "agent": "business_rule",
        "kind": "business_rule",
        "subject_type": "rule",
        "subject_ref": "BR-01",
        "statement": "A line quantity above 99 is rejected.",
        "tag": "confirmed",
        "provenance": {"analyzer": "test@0"},
    }
    values.update(overrides)
    conn.execute(insert(t.claims).values(**values))
    return values["claim_id"]  # type: ignore[no-any-return]


def evidence(conn: Any, claim_id: uuid.UUID) -> None:
    excerpt = "if (qty > MAX_QTY)"
    conn.execute(
        insert(t.evidence).values(
            evidence_id=uuid.uuid4(),
            claim_id=claim_id,
            ref="code:lib/validators.js#L5-L5",
            kind="code",
            excerpt=excerpt,
            excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest(),
        )
    )


def committed_claim(engine: Engine, **overrides: Any) -> uuid.UUID:
    with engine.begin() as conn:
        snapshot(conn)
        claim_id = claim(conn, **overrides)
        evidence(conn, claim_id)
    return claim_id


def test_migration_goes_up_down_up(migrated_engine: Engine) -> None:
    expected = set(t.metadata.tables)
    assert expected <= set(inspect(migrated_engine).get_table_names())
    config = _alembic_config()
    command.downgrade(config, "base")
    assert set(inspect(migrated_engine).get_table_names()) <= {"alembic_version"}
    command.upgrade(config, "head")
    assert expected <= set(inspect(migrated_engine).get_table_names())


def test_table_definitions_match_the_migrated_database(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(context, t.metadata) == []


def test_claim_with_evidence_commits_in_either_order(migrated_engine: Engine) -> None:
    committed_claim(migrated_engine)
    with migrated_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM claims")).scalar_one() == 1


def test_claim_without_evidence_is_rejected_at_commit(migrated_engine: Engine) -> None:
    with (
        pytest.raises(exc.IntegrityError, match="has no evidence"),
        migrated_engine.begin() as conn,
    ):
        snapshot(conn)
        claim(conn)


@pytest.mark.parametrize(
    "overrides",
    [
        {"tag": "inferred"},  # no reasoning or confirm_by
        {"tag": "inferred", "reasoning": "because"},  # no confirm_by
        {"tag": "unknown"},  # no question
        {"tag": "unknown", "question": "why?"},  # no confirm_by
        {"tag": "certain"},  # not a tag
        {"agent": "wizard"},
        {"statement": "   "},
    ],
)
def test_invalid_claims_are_rejected(migrated_engine: Engine, overrides: dict[str, Any]) -> None:
    with pytest.raises(exc.IntegrityError), migrated_engine.begin() as conn:
        snapshot(conn)
        claim(conn, **overrides)


def test_inferred_and_unknown_claims_with_their_required_fields_are_accepted(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as conn:
        snapshot(conn)
        for overrides in (
            {"tag": "inferred", "reasoning": "r", "confirm_by": "run a test"},
            {"tag": "unknown", "question": "which mailer is used?", "confirm_by": "ask owner"},
        ):
            evidence(conn, claim(conn, **overrides))


def test_claims_are_immutable(migrated_engine: Engine) -> None:
    claim_id = committed_claim(migrated_engine)
    with pytest.raises(exc.IntegrityError, match="append-only"), migrated_engine.begin() as conn:
        conn.execute(text("UPDATE claims SET tag = 'unknown' WHERE claim_id = :c"), {"c": claim_id})
    with pytest.raises(exc.IntegrityError, match="append-only"), migrated_engine.begin() as conn:
        conn.execute(text("DELETE FROM evidence"))


def test_a_correction_is_a_new_claim_that_supersedes_the_old(migrated_engine: Engine) -> None:
    old = committed_claim(migrated_engine)
    with migrated_engine.begin() as conn:
        new = claim(conn, supersedes_id=old, statement="A line quantity above 98 is rejected.")
        evidence(conn, new)
    with migrated_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM claims")).scalar_one() == 2


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET actor = 'x'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ],
)
def test_audit_log_is_append_only(migrated_engine: Engine, statement: str) -> None:
    with migrated_engine.begin() as conn:
        conn.execute(
            insert(t.audit_log).values(actor="t", event="e", subject_type="s", subject_id="1")
        )
    with pytest.raises(exc.IntegrityError, match="append-only"), migrated_engine.begin() as conn:
        conn.execute(text(statement))


def test_review_decisions_need_a_reason_and_a_correction_needs_a_new_claim(
    migrated_engine: Engine,
) -> None:
    claim_id = committed_claim(migrated_engine, tag="unknown", question="q", confirm_by="c")
    item_id = uuid.uuid4()
    with migrated_engine.begin() as conn:
        conn.execute(
            insert(t.review_items).values(
                item_id=item_id,
                claim_id=claim_id,
                trigger="unknown",
                question="q",
                raised_by="business_rule",
            )
        )
    base: dict[str, Any] = {"item_id": item_id, "claim_id": claim_id, "reviewer": "aditya"}
    bad: list[dict[str, Any]] = [
        {"decision": "reject"},  # no reason
        {"decision": "reject", "reason": "  "},
        {"decision": "correct", "reason": "wrong value"},  # no new claim
        {"decision": "confirm", "new_claim_id": claim_id},  # new claim without a correction
        {"decision": "maybe"},
    ]
    for extra in bad:
        with pytest.raises(exc.IntegrityError), migrated_engine.begin() as conn:
            conn.execute(
                insert(t.review_decisions).values(decision_id=uuid.uuid4(), **base, **extra)
            )
    with migrated_engine.begin() as conn:
        conn.execute(
            insert(t.review_decisions).values(decision_id=uuid.uuid4(), decision="defer", **base)
        )


def test_jobs_are_deduplicated_and_never_stall_silently(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        snapshot(conn)
    job: dict[str, Any] = {
        "run_id": uuid.uuid4(),
        "snapshot_id": SNAP,
        "job_type": "discovery",
        "input_hash": "h",
        "dedupe_key": "discovery:h",
    }
    with migrated_engine.begin() as conn:
        conn.execute(insert(t.jobs).values(job_id=uuid.uuid4(), **job))
    with pytest.raises(exc.IntegrityError), migrated_engine.begin() as conn:  # same dedupe key
        conn.execute(insert(t.jobs).values(job_id=uuid.uuid4(), **job))
    other = {**job, "dedupe_key": "other"}
    with pytest.raises(exc.IntegrityError), migrated_engine.begin() as conn:  # dead, no reason
        conn.execute(insert(t.jobs).values(job_id=uuid.uuid4(), state="dead", **other))
    with pytest.raises(exc.IntegrityError), migrated_engine.begin() as conn:  # running, no lock
        conn.execute(insert(t.jobs).values(job_id=uuid.uuid4(), state="running", **other))
    with migrated_engine.begin() as conn:
        conn.execute(
            insert(t.jobs).values(job_id=uuid.uuid4(), state="dead", last_error="boom", **other)
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"snapshot_id": "not-a-hash"},
        {"source_kind": "ftp"},
    ],
)
def test_bad_snapshots_are_rejected(migrated_engine: Engine, overrides: dict[str, Any]) -> None:
    values: dict[str, Any] = {
        "snapshot_id": SNAP,
        "source_kind": "archive",
        "repo_name": "x",
        "platform_version": "0",
        "created_by": "t",
        "manifest": {},
    }
    values.update(overrides)
    with pytest.raises(exc.IntegrityError), migrated_engine.begin() as conn:
        conn.execute(insert(t.snapshots).values(**values))


@pytest.mark.parametrize("path", ["/etc/passwd", "../outside.js", "a/../../b.js"])
def test_snapshot_file_paths_cannot_escape_the_snapshot(migrated_engine: Engine, path: str) -> None:
    with migrated_engine.begin() as conn:
        snapshot(conn)
    with pytest.raises(exc.IntegrityError), migrated_engine.begin() as conn:
        conn.execute(
            insert(t.snapshot_files).values(
                snapshot_id=SNAP, path=path, kind="source", sha256="b" * 64, bytes=1
            )
        )


def test_claim_in_an_unknown_snapshot_is_rejected(migrated_engine: Engine) -> None:
    with pytest.raises(exc.IntegrityError), migrated_engine.begin() as conn:
        claim(conn, snapshot_id="c" * 64)
