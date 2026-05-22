"""POST /codegen — TC 소믈리에가 train.py 전체를 생성.

cq-pcq-tc-dental-codegen-loop: corpus(이전 생성 코드/결과/실패)를 컨텍스트로 web_search
+ CodeGenSynthesizer로 train.py를 합성해 반환한다. cq가 이 코드를 워크스페이스에
배포·실행하고 PCQ로 봉인한다.
"""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from the_commons.api.dependencies import get_evidence_store
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.models import Evidence
from the_commons.library.store import EvidenceStore
from the_commons.matchmaker.code_synthesizer import (
    CodeAttempt,
    CodeGenSynthesizer,
    OpenAIWebSearchCodeGenLLM,
)

router = APIRouter(tags=["codegen"])


class CodegenRequest(BaseModel):
    """data_dirs: 데이터 루트의 디렉토리 목록(자율 탐색 컨텍스트). intent: 목표."""

    data_dirs: list[str]
    intent: str
    modality: str = "vision"


class CodegenResponse(BaseModel):
    recipe_id: str
    generated_code: str | None
    requirements: list[str]
    sources: list[str]
    reasoning: str
    corpus_size: int


async def get_codegen_synth() -> CodeGenSynthesizer:
    """production CodeGenSynthesizer — OpenAI web_search. test는 override."""
    return CodeGenSynthesizer(llm=OpenAIWebSearchCodeGenLLM())


def _evidence_to_attempt(ev: Evidence) -> CodeAttempt:
    """evidence → CodeAttempt (코드 환류 컨텍스트). 코드는 pcq_record.code.content."""
    pcq = ev.pcq_record
    code = getattr(pcq, "code", None)
    code_obj = code if isinstance(code, dict) else (code.model_dump() if code else {})
    metrics = dict(pcq.metrics) if pcq.metrics else {}
    failed = bool(metrics.get("failed"))
    recipe_id = (pcq.config or {}).get("recipe_id", "experiment")
    return CodeAttempt(
        recipe_id=recipe_id,
        metrics={k: v for k, v in metrics.items() if k not in ("failed", "exit_code", "stderr_tail")},
        failed=failed,
        code_summary=recipe_id,
        error=str(metrics.get("stderr_tail") or "")[-400:] if failed else None,
        full_code=code_obj.get("content") if isinstance(code_obj, dict) else None,
    )


@router.post("/codegen", response_model=CodegenResponse)
async def codegen(
    body: CodegenRequest,
    claims: VerifiedClaims = Depends(require_contributor),
    store: EvidenceStore = Depends(get_evidence_store),
    synth: CodeGenSynthesizer = Depends(get_codegen_synth),
) -> CodegenResponse:
    """corpus 환류 + web_search → train.py 생성."""
    evidences, total = await store.list_evidence(
        modality=body.modality, limit=50, deprecated=False
    )
    # list_evidence는 created_at DESC(최근 먼저). CodeGenSynthesizer는 corpus[-8:]를
    # "최근"으로 보므로 reversed로 뒤집어 최근 시도(현재 task의 실패 traceback 포함)가
    # 컨텍스트에 들어가게 한다.
    corpus = [_evidence_to_attempt(ev) for ev in reversed(evidences)]
    proposal = await synth.propose(
        data_dirs=body.data_dirs, intent=body.intent, corpus=corpus
    )
    return CodegenResponse(
        recipe_id=proposal.recipe_id,
        generated_code=proposal.generated_code,
        requirements=proposal.requirements,
        sources=proposal.sources,
        reasoning=proposal.reasoning,
        corpus_size=total,
    )
