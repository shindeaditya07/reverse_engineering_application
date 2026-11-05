"""Turn a verdict into `verification_results` row values. Pure: no database access."""

import uuid
from typing import Any

from services.verifier.models import Verdict


def result_rows(verdict: Verdict, claim_version_id: uuid.UUID) -> list[dict[str, Any]]:
    """One row per check that ran. `detail` holds check IDs, paths and counts, never a value."""
    return [
        {
            "claim_version_id": claim_version_id,
            "check_id": r.check_id,
            "passed": r.passed,
            "detail": r.detail,
        }
        for r in verdict.results
    ]
