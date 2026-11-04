"""initial claim store

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.String(length=80), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(length=40), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=10), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="status"),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "job_type", "input_hash", name="uq_job_identity"),
    )
    op.create_index(op.f("ix_jobs_run_id"), "jobs", ["run_id"], unique=False)
    op.create_table(
        "model_calls",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("tokens_in >= 0 AND tokens_out >= 0 AND latency_ms >= 0", name="counts"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_model_calls_run_id"), "model_calls", ["run_id"], unique=False)
    op.create_table(
        "snapshots",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("revision", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_kind IN ('github', 'local_path', 'archive')", name="source_kind"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_kind", "source_ref", "revision", name="uq_snapshot_revision"),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["snapshots.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_artifacts_run_id"), "artifacts", ["run_id"], unique=False)
    op.create_index(op.f("ix_artifacts_snapshot_id"), "artifacts", ["snapshot_id"], unique=False)
    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["snapshots.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_claims_run_id"), "claims", ["run_id"], unique=False)
    op.create_index(op.f("ix_claims_snapshot_id"), "claims", ["snapshot_id"], unique=False)
    op.create_table(
        "snapshot_files",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("is_generated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_vendored", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["snapshots.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "path", name="uq_snapshot_file_path"),
    )
    op.create_index(
        op.f("ix_snapshot_files_snapshot_id"), "snapshot_files", ["snapshot_id"], unique=False
    )
    op.create_table(
        "claim_versions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("producer", sa.String(length=80), nullable=False),
        sa.Column("producer_kind", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "producer_kind IN ('deterministic', 'test', 'model', 'human')", name="producer_kind"
        ),
        sa.CheckConstraint(
            "status <> 'confirmed' OR producer_kind IN ('deterministic', 'test')",
            name="confirmed_not_model_only",
        ),
        sa.CheckConstraint("status IN ('confirmed', 'inferred', 'unknown')", name="status"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_id", "version", name="uq_claim_version"),
    )
    op.create_index(
        op.f("ix_claim_versions_claim_id"), "claim_versions", ["claim_id"], unique=False
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("claim_version_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("object_name", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "kind <> 'file_range' OR (path IS NOT NULL AND start_line >= 1 AND end_line >= start_line AND end_line - start_line + 1 <= 40)",
            name="file_range_valid",
        ),
        sa.CheckConstraint(
            "kind = 'file_range' OR object_name IS NOT NULL OR path IS NOT NULL", name="has_locator"
        ),
        sa.CheckConstraint(
            "kind IN ('file_range', 'schema_object', 'config_key', 'build_step', 'log_line', 'ticket')",
            name="kind",
        ),
        sa.ForeignKeyConstraint(
            ["claim_version_id"],
            ["claim_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["snapshots.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_evidence_claim_version_id"), "evidence", ["claim_version_id"], unique=False
    )
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("claim_version_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("reviewer", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("decision IN ('accept', 'edit', 'reject')", name="decision"),
        sa.CheckConstraint("length(reviewer) > 0", name="reviewer_present"),
        sa.ForeignKeyConstraint(
            ["claim_version_id"],
            ["claim_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_review_decisions_claim_version_id"),
        "review_decisions",
        ["claim_version_id"],
        unique=False,
    )
    op.create_table(
        "review_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("claim_version_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=10), server_default=sa.text("'open'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason IN ('unknown', 'inferred', 'stale', 'verifier_failure')", name="reason"
        ),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="status"),
        sa.ForeignKeyConstraint(
            ["claim_version_id"],
            ["claim_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_review_items_claim_version_id"), "review_items", ["claim_version_id"], unique=False
    )
    op.create_table(
        "verification_results",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("claim_version_id", sa.Uuid(), nullable=False),
        sa.Column("check_id", sa.String(length=5), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("check_id ~ '^V-([1-9]|10)$'", name="check_id"),
        sa.ForeignKeyConstraint(
            ["claim_version_id"],
            ["claim_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_verification_results_claim_version_id"),
        "verification_results",
        ["claim_version_id"],
        unique=False,
    )

    # Append-only tables (REV-1.2, NFR-5, CLM-1.5): no UPDATE, DELETE or TRUNCATE, ever.
    op.execute(
        """
        CREATE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    for table in ("review_decisions", "audit_log", "claim_versions"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_change()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_change()"
        )

    # EVD-1.1: a Confirmed or Inferred claim version needs at least one evidence row by commit.
    op.execute(
        """
        CREATE FUNCTION require_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.status IN ('confirmed', 'inferred') AND NOT EXISTS (
                SELECT 1 FROM evidence WHERE claim_version_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'claim version % (%) has no evidence', NEW.id, NEW.status
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER claim_versions_require_evidence AFTER INSERT ON claim_versions "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_evidence()"
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_verification_results_claim_version_id"), table_name="verification_results"
    )
    op.drop_table("verification_results")
    op.drop_index(op.f("ix_review_items_claim_version_id"), table_name="review_items")
    op.drop_table("review_items")
    op.drop_index(op.f("ix_review_decisions_claim_version_id"), table_name="review_decisions")
    op.drop_table("review_decisions")
    op.drop_index(op.f("ix_evidence_claim_version_id"), table_name="evidence")
    op.drop_table("evidence")
    op.drop_index(op.f("ix_claim_versions_claim_id"), table_name="claim_versions")
    op.drop_table("claim_versions")
    op.drop_index(op.f("ix_snapshot_files_snapshot_id"), table_name="snapshot_files")
    op.drop_table("snapshot_files")
    op.drop_index(op.f("ix_claims_snapshot_id"), table_name="claims")
    op.drop_index(op.f("ix_claims_run_id"), table_name="claims")
    op.drop_table("claims")
    op.drop_index(op.f("ix_artifacts_snapshot_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_run_id"), table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_table("snapshots")
    op.drop_index(op.f("ix_model_calls_run_id"), table_name="model_calls")
    op.drop_table("model_calls")
    op.drop_index(op.f("ix_jobs_run_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("audit_log")
    op.execute("DROP FUNCTION IF EXISTS require_evidence()")
    op.execute("DROP FUNCTION IF EXISTS forbid_change()")
