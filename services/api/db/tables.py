"""Table definitions for the claim store (spec section 12, AGENTS.md section 8).

The Alembic migration is the source of truth for the schema; ``tests/test_claim_store.py``
fails if this metadata and the migrated database disagree, so the two cannot drift.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

metadata = MetaData()

TAGS = ("confirmed", "inferred", "unknown")
AGENTS = (
    "discovery",
    "code_analysis",
    "business_rule",
    "data",
    "diagram",
    "documentation",
    "test",
    "verification",
    "modernization",
    "human",
)
EVIDENCE_KINDS = ("code", "schema", "config", "build", "log", "doc", "graph", "test", "review")
FILE_KINDS = ("source", "schema", "config", "build", "log", "ticket", "doc")
ROLES = ("supports", "contradicts", "context")
REVIEW_TRIGGERS = (
    "unknown",
    "conflict",
    "high_impact_inferred",
    "verification_failed_twice",
    "verification_error",
    "unresolved_dynamic",
)
DECISIONS = ("confirm", "correct", "reject", "defer")
JOB_STATES = ("queued", "running", "succeeded", "failed", "dead")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


snapshots = Table(
    "snapshots",
    metadata,
    Column("snapshot_id", Text, primary_key=True),
    Column("source_kind", Text, nullable=False),
    Column("repo_name", Text, nullable=False),
    Column("commit_sha", Text),
    Column("archive_sha256", Text),
    Column("platform_version", Text, nullable=False),
    Column("created_by", Text, nullable=False),
    Column("manifest", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("snapshot_id ~ '^[0-9a-f]{64}$'", name="ck_snapshots_id_sha256"),
    CheckConstraint(_in("source_kind", ("git", "archive")), name="ck_snapshots_source_kind"),
)

snapshot_files = Table(
    "snapshot_files",
    metadata,
    Column("snapshot_id", Text, ForeignKey("snapshots.snapshot_id"), nullable=False),
    Column("path", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("bytes", BigInteger, nullable=False),
    Column("encoding", Text),
    PrimaryKeyConstraint("snapshot_id", "path"),
    CheckConstraint(_in("kind", FILE_KINDS), name="ck_snapshot_files_kind"),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_snapshot_files_sha256"),
    CheckConstraint("bytes >= 0", name="ck_snapshot_files_bytes"),
    CheckConstraint("path !~ '(^/|\\.\\.)'", name="ck_snapshot_files_path_relative"),
)

claims = Table(
    "claims",
    metadata,
    Column("claim_id", UUID(as_uuid=True), primary_key=True),
    Column("snapshot_id", Text, ForeignKey("snapshots.snapshot_id"), nullable=False),
    Column("supersedes_id", UUID(as_uuid=True), ForeignKey("claims.claim_id")),
    Column("agent", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("subject_type", Text, nullable=False),
    Column("subject_ref", Text, nullable=False),
    Column("statement", Text, nullable=False),
    Column("tag", Text, nullable=False),
    Column("reasoning", Text),
    Column("confirm_by", Text),
    Column("question", Text),
    Column("categories", ARRAY(Text), nullable=False, server_default="{}"),
    Column("policy_refs", ARRAY(Text), nullable=False, server_default="{}"),
    Column("depends_on", ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"),
    Column("provenance", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(_in("tag", TAGS), name="ck_claims_tag"),
    CheckConstraint(_in("agent", AGENTS), name="ck_claims_agent"),
    CheckConstraint("length(btrim(statement)) > 0", name="ck_claims_statement_not_blank"),
    # V-6: an Inferred claim carries its reasoning and how to confirm it ...
    CheckConstraint(
        "tag <> 'inferred' OR (reasoning IS NOT NULL AND confirm_by IS NOT NULL)",
        name="ck_claims_inferred_has_reasoning",
    ),
    # ... and an Unknown claim carries the question and where the answer might come from.
    CheckConstraint(
        "tag <> 'unknown' OR (question IS NOT NULL AND confirm_by IS NOT NULL)",
        name="ck_claims_unknown_has_question",
    ),
    CheckConstraint("supersedes_id IS NULL OR supersedes_id <> claim_id", name="ck_claims_no_self"),
)
Index(
    "ix_claims_snapshot_subject", claims.c.snapshot_id, claims.c.subject_type, claims.c.subject_ref
)
Index("ix_claims_snapshot_tag", claims.c.snapshot_id, claims.c.tag)

evidence = Table(
    "evidence",
    metadata,
    Column("evidence_id", UUID(as_uuid=True), primary_key=True),
    Column("claim_id", UUID(as_uuid=True), ForeignKey("claims.claim_id"), nullable=False),
    Column("ref", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("excerpt", Text, nullable=False),
    Column("excerpt_sha256", Text, nullable=False),
    Column("role", Text, nullable=False, server_default="supports"),
    CheckConstraint(_in("kind", EVIDENCE_KINDS), name="ck_evidence_kind"),
    CheckConstraint(_in("role", ROLES), name="ck_evidence_role"),
    CheckConstraint("excerpt_sha256 ~ '^[0-9a-f]{64}$'", name="ck_evidence_sha256"),
    CheckConstraint("ref ~ '^[a-z]+:.+'", name="ck_evidence_ref_shape"),
)
Index("ix_evidence_claim", evidence.c.claim_id)

verification_results = Table(
    "verification_results",
    metadata,
    Column("result_id", UUID(as_uuid=True), primary_key=True),
    Column("claim_id", UUID(as_uuid=True), ForeignKey("claims.claim_id"), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("rule_failures", JSONB, nullable=False, server_default="[]"),
    Column("judge", JSONB),
    Column("verifier_version", Text, nullable=False),
    Column("verified_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        _in("status", ("passed", "failed", "downgraded", "error")),
        name="ck_verification_status",
    ),
    CheckConstraint("attempt >= 1", name="ck_verification_attempt"),
)
Index("ix_verification_claim", verification_results.c.claim_id)

review_items = Table(
    "review_items",
    metadata,
    Column("item_id", UUID(as_uuid=True), primary_key=True),
    Column("claim_id", UUID(as_uuid=True), ForeignKey("claims.claim_id"), nullable=False),
    Column("trigger", Text, nullable=False),
    Column("question", Text, nullable=False),
    Column("raised_by", Text, nullable=False),
    Column("high_impact", Boolean, nullable=False, server_default="false"),
    Column("status", Text, nullable=False, server_default="open"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("resolved_at", DateTime(timezone=True)),
    CheckConstraint(_in("trigger", REVIEW_TRIGGERS), name="ck_review_items_trigger"),
    CheckConstraint(_in("status", ("open", "resolved")), name="ck_review_items_status"),
    CheckConstraint(
        "(status = 'resolved') = (resolved_at IS NOT NULL)", name="ck_review_items_resolved_at"
    ),
)
Index("ix_review_items_status", review_items.c.status)

review_decisions = Table(
    "review_decisions",
    metadata,
    Column("decision_id", UUID(as_uuid=True), primary_key=True),
    Column("item_id", UUID(as_uuid=True), ForeignKey("review_items.item_id"), nullable=False),
    # The claim version the reviewer actually saw (REV-5.3).
    Column("claim_id", UUID(as_uuid=True), ForeignKey("claims.claim_id"), nullable=False),
    Column("decision", Text, nullable=False),
    Column("reviewer", Text, nullable=False),
    Column("reason", Text),
    Column("new_claim_id", UUID(as_uuid=True), ForeignKey("claims.claim_id")),
    Column("decided_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(_in("decision", DECISIONS), name="ck_review_decisions_decision"),
    CheckConstraint(
        "decision NOT IN ('correct', 'reject') "
        "OR (reason IS NOT NULL AND length(btrim(reason)) > 0)",
        name="ck_review_decisions_reason_required",
    ),
    CheckConstraint(
        "(decision = 'correct') = (new_claim_id IS NOT NULL)",
        name="ck_review_decisions_correct_has_new_claim",
    ),
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("audit_id", BigInteger, primary_key=True, autoincrement=True),
    Column("at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("actor", Text, nullable=False),
    Column("event", Text, nullable=False),
    Column("subject_type", Text, nullable=False),
    Column("subject_id", Text, nullable=False),
    Column("details", JSONB, nullable=False, server_default="{}"),
)
Index("ix_audit_subject", audit_log.c.subject_type, audit_log.c.subject_id)

jobs = Table(
    "jobs",
    metadata,
    Column("job_id", UUID(as_uuid=True), primary_key=True),
    Column("run_id", UUID(as_uuid=True), nullable=False),
    Column("snapshot_id", Text, ForeignKey("snapshots.snapshot_id"), nullable=False),
    Column("job_type", Text, nullable=False),
    Column("input_hash", Text, nullable=False),
    Column("dedupe_key", Text, nullable=False, unique=True),
    Column("state", Text, nullable=False, server_default="queued"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("max_attempts", Integer, nullable=False, server_default="3"),
    Column("run_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("locked_at", DateTime(timezone=True)),
    Column("last_error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(_in("state", JOB_STATES), name="ck_jobs_state"),
    CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_jobs_attempts"),
    # A dead job must say why (ReplyDesk ADR-0002): nothing stalls silently.
    CheckConstraint("state <> 'dead' OR last_error IS NOT NULL", name="ck_jobs_dead_has_error"),
    CheckConstraint("(state = 'running') = (locked_at IS NOT NULL)", name="ck_jobs_lock"),
)
Index("ix_jobs_claimable", jobs.c.state, jobs.c.run_at)

__all__ = [
    "audit_log",
    "claims",
    "evidence",
    "jobs",
    "metadata",
    "review_decisions",
    "review_items",
    "snapshot_files",
    "snapshots",
    "verification_results",
]
