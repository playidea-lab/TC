"""GET /evidence/{id} — Library L1 read with server-derived verifier."""

from fastapi import APIRouter, Depends, HTTPException, status

from the_commons.api.dependencies import (
    get_evidence_store,
    get_reciprocity_store,
)
from the_commons.api.schemas import EvidenceReadResponse
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.store import EvidenceStore
from the_commons.reciprocity.event_store import ReciprocityEventStore

router = APIRouter(tags=["evidence"])


@router.get("/evidence/{evidence_id}", response_model=EvidenceReadResponse)
async def read_evidence(
    evidence_id: str,
    claims: VerifiedClaims = Depends(require_contributor),
    store: EvidenceStore = Depends(get_evidence_store),
    reciprocity: ReciprocityEventStore = Depends(get_reciprocity_store),
) -> EvidenceReadResponse:
    """ID로 evidence 한 건 반환. synthetic이면 verifier를 event store에서 derive.

    record 자체는 L1 immutable. verifier는 응답 시 read-time JOIN으로 채워짐.
    """
    _ = claims
    evidence = await store.get_by_id(evidence_id)
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"evidence not found: {evidence_id}",
        )

    # synthetic tier만 verifier derive (real은 검증 대상이 아니라 검증자)
    if evidence.tier == "synthetic" and evidence.synthetic_source is not None:
        verifier = await reciprocity.find_verifier_for(evidence_id)
        if verifier is not None:
            # Pydantic model_copy로 immutable 사본에 derived field만 갱신
            evidence = evidence.model_copy(
                update={
                    "synthetic_source": evidence.synthetic_source.model_copy(
                        update={"verifier": verifier}
                    )
                }
            )

    return EvidenceReadResponse(evidence=evidence)
