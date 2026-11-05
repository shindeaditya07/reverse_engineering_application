"""The verifier: deterministic code that decides which claims may stand (VER-1.1, VER-1.3)."""

from services.verifier.flags import FileFlags, detect_flags
from services.verifier.models import (
    CheckResult,
    ClaimInput,
    DocSentence,
    EvidenceInput,
    SentenceResult,
    Verdict,
)
from services.verifier.rows import result_rows
from services.verifier.verify import verify_claim, verify_claims, verify_document

__all__ = [
    "CheckResult",
    "ClaimInput",
    "DocSentence",
    "EvidenceInput",
    "FileFlags",
    "SentenceResult",
    "Verdict",
    "detect_flags",
    "result_rows",
    "verify_claim",
    "verify_claims",
    "verify_document",
]
