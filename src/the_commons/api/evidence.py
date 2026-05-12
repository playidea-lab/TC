"""GET /evidence/{id} — Library L1 read."""

from fastapi import APIRouter, Depends, HTTPException, status

from the_commons.api.dependencies import get_evidence_store
from the_commons.api.schemas import EvidenceReadResponse
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.store import EvidenceStore

router = APIRouter(tags=["evidence"])


@router.get("/evidence/{evidence_id}", response_model=EvidenceReadResponse)
async def read_evidence(
    evidence_id: str,
    claims: VerifiedClaims = Depends(require_contributor),
    store: EvidenceStore = Depends(get_evidence_store),
) -> EvidenceReadResponse:
    """ID로 evidence 한 건을 immutable 형태로 반환."""
    _ = claims
    evidence = await store.get_by_id(evidence_id)
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"evidence not found: {evidence_id}",
        )
    return EvidenceReadResponse(evidence=evidence)
