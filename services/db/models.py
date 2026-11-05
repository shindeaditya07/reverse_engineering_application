"""Claim store schema (docs/spec.md section 10, AGENTS.md section 8).

Design rules enforced in the database, not by convention:
- review_decisions and audit_log are append-only (REV-1.2): triggers in migration 0001.
- Claims are versioned: claim_versions rows are never updated or deleted (CLM-1.5).
- There is no "accepted" column anywhere. A claim is accepted only through a review decision
  (REV-1.1), so no code path can mark one accepted without recording who decided.
- A model alone never produces a Confirmed claim (CLM-1.2): CHECK on producer_kind.
- A Confirmed or Inferred claim version must have evidence (EVD-1.1): deferred constraint
  trigger in migration 0001.
- A file-range evidence span is at most 40 lines (EVD-1.4, rules_constants.yaml); the literal is
  asserted against the constants file by tests/test_db_schema.py.
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))


def _created() -> Mapped[dt.datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Snapshot(Base):
    """A pinned revision of a legacy source (SEC-1.6): commit SHA or working-tree hash."""

    __tablename__ = "snapshots"
    __table_args__ = (
        CheckConstraint("source_kind IN ('github', 'local_path', 'archive')", name="source_kind"),
        UniqueConstraint("source_kind", "source_ref", "revision", name="uq_snapshot_revision"),
    )

    id: Mapped[uuid.UUID] = _id()
    source_kind: Mapped[str] = mapped_column(String(20))
    source_ref: Mapped[str] = mapped_column(Text)
    revision: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = _created()


class SnapshotFile(Base):
    __tablename__ = "snapshot_files"
    __table_args__ = (UniqueConstraint("snapshot_id", "path", name="uq_snapshot_file_path"),)

    id: Mapped[uuid.UUID] = _id()
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("snapshots.id"), index=True)
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    is_generated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_vendored: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class Claim(Base):
    """Identity of a claim. Its text and status live in append-only claim_versions."""

    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = _id()
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("snapshots.id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[dt.datetime] = _created()


class ClaimVersion(Base):
    __tablename__ = "claim_versions"
    __table_args__ = (
        UniqueConstraint("claim_id", "version", name="uq_claim_version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("status IN ('confirmed', 'inferred', 'unknown')", name="status"),
        CheckConstraint(
            "producer_kind IN ('deterministic', 'test', 'model', 'human')", name="producer_kind"
        ),
        # CLM-1.2: a model alone never produces Confirmed.
        CheckConstraint(
            "status <> 'confirmed' OR producer_kind IN ('deterministic', 'test')",
            name="confirmed_not_model_only",
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12))
    producer: Mapped[str] = mapped_column(String(80))
    producer_kind: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[dt.datetime] = _created()


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('file_range', 'schema_object', 'config_key', 'build_step', "
            "'log_line', 'ticket')",
            name="kind",
        ),
        # EVD-1.2 and EVD-1.4: a file range has a path and lines, from 1, at most 40 lines.
        CheckConstraint(
            "kind <> 'file_range' OR (path IS NOT NULL AND start_line >= 1 "
            "AND end_line >= start_line AND end_line - start_line + 1 <= 40)",
            name="file_range_valid",
        ),
        CheckConstraint(
            "kind = 'file_range' OR object_name IS NOT NULL OR path IS NOT NULL",
            name="has_locator",
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    claim_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claim_versions.id"), index=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("snapshots.id"))
    kind: Mapped[str] = mapped_column(String(20))
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    object_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))


class VerificationResult(Base):
    __tablename__ = "verification_results"
    __table_args__ = (CheckConstraint("check_id ~ '^V-([1-9]|10)$'", name="check_id"),)

    id: Mapped[uuid.UUID] = _id()
    claim_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claim_versions.id"), index=True)
    check_id: Mapped[str] = mapped_column(String(5))
    passed: Mapped[bool] = mapped_column(Boolean)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = _created()


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'resolved')", name="status"),
        CheckConstraint(
            "reason IN ('unknown', 'inferred', 'stale', 'verifier_failure')", name="reason"
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    claim_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claim_versions.id"), index=True)
    reason: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), server_default=text("'open'"))
    created_at: Mapped[dt.datetime] = _created()


class ReviewDecision(Base):
    """Append-only (REV-1.2): who decided what, when and why."""

    __tablename__ = "review_decisions"
    __table_args__ = (
        CheckConstraint("decision IN ('accept', 'edit', 'reject')", name="decision"),
        CheckConstraint("length(reviewer) > 0", name="reviewer_present"),
    )

    id: Mapped[uuid.UUID] = _id()
    claim_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claim_versions.id"), index=True)
    decision: Mapped[str] = mapped_column(String(10))
    reviewer: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = _id()
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("snapshots.id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    path: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = _created()


class AuditLog(Base):
    """Append-only (NFR-5). detail must never hold source text or secrets (SEC-1.3)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80))
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class Job(Base):
    """DB-backed job; idempotent per (run_id, job_type, input_hash) (AGENTS.md section 4)."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("run_id", "job_type", "input_hash", name="uq_job_identity"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="status"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
    )

    id: Mapped[uuid.UUID] = _id()
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    job_type: Mapped[str] = mapped_column(String(40))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(10), server_default=text("'queued'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = _created()
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModelCall(Base):
    """One model call. Never stores prompt or reply text, only hashes and counts (AGENTS.md 5)."""

    __tablename__ = "model_calls"
    __table_args__ = (
        CheckConstraint("tokens_in >= 0 AND tokens_out >= 0 AND latency_ms >= 0", name="counts"),
    )

    id: Mapped[uuid.UUID] = _id()
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    model: Mapped[str] = mapped_column(String(120))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    tokens_in: Mapped[int] = mapped_column(Integer)
    tokens_out: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = _created()
