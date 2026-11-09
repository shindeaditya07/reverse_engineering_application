"""Store the Business Rule agent's claims through the claim writer. Nothing is stored unverified.

The writer runs V-1 to V-10 and stores a claim the verifier blocks as Unknown in the review queue
(VER-1.1, VER-1.6): this is where a failing sentence is demoted.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.businessrule.agent import RuleAnalysis
from services.businessrule.run import to_claim_input
from services.claims import StoredClaim, verify_and_store
from services.evidence import SnapshotReader

PRODUCER = "businessrule@1"


async def store_rules(
    session: AsyncSession,
    snapshot_id: uuid.UUID,
    run_id: uuid.UUID,
    found: RuleAnalysis,
    reader: SnapshotReader,
) -> list[StoredClaim]:
    """Verify and store every finding. Idempotent per run and claim key."""
    return [
        await verify_and_store(
            session,
            snapshot_id=snapshot_id,
            run_id=run_id,
            kind=finding.kind,
            claim=to_claim_input(finding, reader),
            producer=PRODUCER,
            reader=reader,
        )
        for finding in found.findings
    ]
