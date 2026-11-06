"""Store the Data agent's findings through the claim writer. Nothing is stored unverified."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.claims import StoredClaim, verify_and_store
from services.data.agent import DataAnalysis
from services.discovery.agent import to_claim_inputs
from services.evidence import SnapshotReader

PRODUCER = "data@1"


async def store_data(
    session: AsyncSession,
    snapshot_id: uuid.UUID,
    run_id: uuid.UUID,
    found: DataAnalysis,
    reader: SnapshotReader,
) -> list[StoredClaim]:
    """Verify and store every finding. Safe to call again for the same run: a finding already
    stored is returned unchanged (idempotent per run and claim key)."""
    return [
        await verify_and_store(
            session,
            snapshot_id=snapshot_id,
            run_id=run_id,
            kind=finding.kind,
            claim=to_claim_inputs(finding, reader),
            producer=PRODUCER,
            reader=reader,
        )
        for finding in found.findings
    ]
