"""initial claim store

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("audit_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index("ix_audit_subject", "audit_log", ["subject_type", "subject_id"], unique=False)
    op.create_table(
        "snapshots",
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("repo_name", sa.Text(), nullable=False),
        sa.Column("commit_sha", sa.Text(), nullable=True),
        sa.Column("archive_sha256", sa.Text(), nullable=True),
        sa.Column("platform_version", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("snapshot_id ~ '^[0-9a-f]{64}$'", name="ck_snapshots_id_sha256"),
        sa.CheckConstraint("source_kind IN ('git', 'archive')", name="ck_snapshots_source_kind"),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_table(
        "claims",
        sa.Column("claim_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_ref", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("tag", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("confirm_by", sa.Text(), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("categories", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("policy_refs", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("depends_on", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "agent IN ('discovery', 'code_analysis', 'business_rule', 'data', 'diagram', 'documentation', 'test', 'verification', 'modernization', 'human')",
            name="ck_claims_agent",
        ),
        sa.CheckConstraint(
            "tag <> 'inferred' OR (reasoning IS NOT NULL AND confirm_by IS NOT NULL)",
            name="ck_claims_inferred_has_reasoning",
        ),
        sa.CheckConstraint(
            "tag <> 'unknown' OR (question IS NOT NULL AND confirm_by IS NOT NULL)",
            name="ck_claims_unknown_has_question",
        ),
        sa.CheckConstraint("tag IN ('confirmed', 'inferred', 'unknown')", name="ck_claims_tag"),
        sa.CheckConstraint("length(btrim(statement)) > 0", name="ck_claims_statement_not_blank"),
        sa.CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> claim_id", name="ck_claims_no_self"
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["snapshots.snapshot_id"],
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["claims.claim_id"],
        ),
        sa.PrimaryKeyConstraint("claim_id"),
    )
    op.create_index(
        "ix_claims_snapshot_subject",
        "claims",
        ["snapshot_id", "subject_type", "subject_ref"],
        unique=False,
    )
    op.create_index("ix_claims_snapshot_tag", "claims", ["snapshot_id", "tag"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("(state = 'running') = (locked_at IS NOT NULL)", name="ck_jobs_lock"),
        sa.CheckConstraint(
            "state <> 'dead' OR last_error IS NOT NULL", name="ck_jobs_dead_has_error"
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed', 'dead')", name="ck_jobs_state"
        ),
        sa.CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_jobs_attempts"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["snapshots.snapshot_id"],
        ),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index("ix_jobs_claimable", "jobs", ["state", "run_at"], unique=False)
    op.create_table(
        "snapshot_files",
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("encoding", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('source', 'schema', 'config', 'build', 'log', 'ticket', 'doc')",
            name="ck_snapshot_files_kind",
        ),
        sa.CheckConstraint("path !~ '(^/|\\.\\.)'", name="ck_snapshot_files_path_relative"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_snapshot_files_sha256"),
        sa.CheckConstraint("bytes >= 0", name="ck_snapshot_files_bytes"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["snapshots.snapshot_id"],
        ),
        sa.PrimaryKeyConstraint("snapshot_id", "path"),
    )
    op.create_table(
        "evidence",
        sa.Column("evidence_id", sa.UUID(), nullable=False),
        sa.Column("claim_id", sa.UUID(), nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("excerpt_sha256", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), server_default="supports", nullable=False),
        sa.CheckConstraint("excerpt_sha256 ~ '^[0-9a-f]{64}$'", name="ck_evidence_sha256"),
        sa.CheckConstraint(
            "kind IN ('code', 'schema', 'config', 'build', 'log', 'doc', 'graph', 'test', 'review')",
            name="ck_evidence_kind",
        ),
        sa.CheckConstraint("ref ~ '^[a-z]+:.+'", name="ck_evidence_ref_shape"),
        sa.CheckConstraint(
            "role IN ('supports', 'contradicts', 'context')", name="ck_evidence_role"
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.claim_id"],
        ),
        sa.PrimaryKeyConstraint("evidence_id"),
    )
    op.create_index("ix_evidence_claim", "evidence", ["claim_id"], unique=False)
    op.create_table(
        "review_items",
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("claim_id", sa.UUID(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("raised_by", sa.Text(), nullable=False),
        sa.Column("high_impact", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL)", name="ck_review_items_resolved_at"
        ),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="ck_review_items_status"),
        sa.CheckConstraint(
            "trigger IN ('unknown', 'conflict', 'high_impact_inferred', 'verification_failed_twice', 'verification_error', 'unresolved_dynamic')",
            name="ck_review_items_trigger",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.claim_id"],
        ),
        sa.PrimaryKeyConstraint("item_id"),
    )
    op.create_index("ix_review_items_status", "review_items", ["status"], unique=False)
    op.create_table(
        "verification_results",
        sa.Column("result_id", sa.UUID(), nullable=False),
        sa.Column("claim_id", sa.UUID(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "rule_failures",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("judge", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("verifier_version", sa.Text(), nullable=False),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('passed', 'failed', 'downgraded', 'error')", name="ck_verification_status"
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_verification_attempt"),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.claim_id"],
        ),
        sa.PrimaryKeyConstraint("result_id"),
    )
    op.create_index("ix_verification_claim", "verification_results", ["claim_id"], unique=False)
    op.create_table(
        "review_decisions",
        sa.Column("decision_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("claim_id", sa.UUID(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("new_claim_id", sa.UUID(), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(decision = 'correct') = (new_claim_id IS NOT NULL)",
            name="ck_review_decisions_correct_has_new_claim",
        ),
        sa.CheckConstraint(
            "decision IN ('confirm', 'correct', 'reject', 'defer')",
            name="ck_review_decisions_decision",
        ),
        sa.CheckConstraint(
            "decision NOT IN ('correct', 'reject') OR (reason IS NOT NULL AND length(btrim(reason)) > 0)",
            name="ck_review_decisions_reason_required",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.claim_id"],
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["review_items.item_id"],
        ),
        sa.ForeignKeyConstraint(
            ["new_claim_id"],
            ["claims.claim_id"],
        ),
        sa.PrimaryKeyConstraint("decision_id"),
    )

    # Invariants that the database enforces itself (AGENTS.md section 8), not only the app.
    op.execute("""
        CREATE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'integrity_constraint_violation';
        END $$
    """)
    for table in ("audit_log", "claims", "evidence", "verification_results", "review_decisions"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_change()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_change()"
        )
    # EVD-1.1: a claim with no evidence is not a finding. Checked at commit, so the claim and
    # its evidence can be written in the same transaction in either order.
    op.execute("""
        CREATE FUNCTION require_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM evidence WHERE claim_id = NEW.claim_id) THEN
                RAISE EXCEPTION 'claim % has no evidence', NEW.claim_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NULL;
        END $$
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER claims_need_evidence AFTER INSERT ON claims "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_evidence()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER claims_need_evidence ON claims")
    op.execute("DROP FUNCTION require_evidence()")
    op.drop_table("review_decisions")
    op.drop_index("ix_verification_claim", table_name="verification_results")
    op.drop_table("verification_results")
    op.drop_index("ix_review_items_status", table_name="review_items")
    op.drop_table("review_items")
    op.drop_index("ix_evidence_claim", table_name="evidence")
    op.drop_table("evidence")
    op.drop_table("snapshot_files")
    op.drop_index("ix_jobs_claimable", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_claims_snapshot_tag", table_name="claims")
    op.drop_index("ix_claims_snapshot_subject", table_name="claims")
    op.drop_table("claims")
    op.drop_table("snapshots")
    op.drop_index("ix_audit_subject", table_name="audit_log")
    op.drop_table("audit_log")
    op.execute("DROP FUNCTION forbid_change()")
