"""Inputs and outputs of the verifier. Plain data: no database, no model, no network."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from services.evidence import EvidenceRef

STATUSES = ("confirmed", "inferred", "unknown")
PRODUCER_KINDS = ("deterministic", "test", "model", "human")
# A claim that fails one of these is demoted to Unknown. V-3 only marks it stale; V-4, V-7 and
# V-9 block it without changing what it says. This split is a proposal (docs/verifier.md).
DEMOTING_CHECKS = frozenset({"V-1", "V-2", "V-5", "V-6", "V-10"})


@dataclass(frozen=True)
class EvidenceInput:
    """One cited reference as stored or as a model proposed it, plus the hash stored with it."""

    ref: Mapping[str, Any] | EvidenceRef
    content_hash: str | None


@dataclass(frozen=True)
class ClaimInput:
    claim_id: str
    text: str
    status: str
    producer_kind: str
    evidence: tuple[EvidenceInput, ...] = ()
    explanation: str | None = None
    # Paths the claim is about. Citing a generated or vendored file is allowed only for these.
    subject_paths: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    passed: bool
    detail: str | None = None


@dataclass(frozen=True)
class Verdict:
    claim_id: str
    input_status: str
    final_status: str
    results: tuple[CheckResult, ...]
    stale: bool

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    @property
    def passed(self) -> bool:
        return not self.failures and not self.stale

    @property
    def queue_reason(self) -> str | None:
        """Why the claim goes to the review queue (REV-2.1), or None if it needs no queueing."""
        if self.failures:
            return "verifier_failure"
        if self.stale:
            return "stale"
        if self.final_status in ("unknown", "inferred"):
            return self.final_status
        return None


@dataclass(frozen=True)
class DocSentence:
    text: str
    claim_ids: tuple[str, ...]


@dataclass(frozen=True)
class SentenceResult:
    index: int
    passed: bool
    reason: str | None = None
