"""CodeGenSynthesizer — train.py 전체를 생성하는 소믈리에.

cq-pcq-tc-dental-codegen-loop: web_search로 최신 기법을 조사하고, corpus(이전 생성
코드/결과/실패)를 컨텍스트로 train.py 전체 + requirements를 합성한다. cq가 이 코드를
워크스페이스에 배포해 실행하고, PCQ가 코드를 sha256 봉인한다.

계약: 생성 코드는 `--data-root` 인자를 받고, stdout에 `@image_auroc= @pixel_auroc=`를
출력하며, 데이터 형태는 코드가 직접 탐색한다(자율). 실패(LLM/파싱)는 RR6로 degrade —
직전 성공 코드 재시도 또는 최소 stub.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import structlog

from the_commons.matchmaker.synthesizer import NextConfigProposal

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@runtime_checkable
class CodeGenLLM(Protocol):
    """web_search 가능한 LLM. (text, sources) 반환."""

    async def generate(self, prompt: str) -> tuple[str, list[str]]: ...


@dataclass(frozen=True)
class CodeAttempt:
    """corpus의 이전 코드 시도 1건 — 다음 생성의 컨텍스트."""

    recipe_id: str
    metrics: dict[str, Any]
    failed: bool
    code_summary: str = ""
    error: str | None = None
    full_code: str | None = None  # degrade(직전 성공 코드 재시도)용


# 계약 준수 최소 stub — LLM 완전 실패 + corpus 없을 때
_STUB_CODE = (
    "import argparse, os\n"
    "p = argparse.ArgumentParser()\n"
    "p.add_argument('--data-root', default='.')\n"
    "a = p.parse_args()\n"
    "print('stub: data_root', a.data_root, 'exists', os.path.isdir(a.data_root), flush=True)\n"
    "print('@image_auroc=0.5 @pixel_auroc=0.5', flush=True)\n"
)


def _extract_code_block(text: str) -> str | None:
    """```python ... ``` 또는 ``` ... ``` 첫 블록 추출."""
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


def _extract_requirements(text: str) -> list[str]:
    """`requirements: [...]` JSON 리스트 추출. 실패 시 빈 리스트."""
    m = re.search(r"requirements\s*[:=]\s*(\[[^\]]*\])", text, re.IGNORECASE)
    if not m:
        return []
    try:
        reqs = json.loads(m.group(1))
        return [str(r) for r in reqs if isinstance(r, str)]
    except (json.JSONDecodeError, ValueError):
        return []


def _build_prompt(
    data_dirs: list[str], intent: str, corpus: list[CodeAttempt]
) -> str:
    """코드 생성 프롬프트 — web_search 조사 + corpus 환류 + 계약."""
    dirs_block = "\n".join(f"  - {d}" for d in data_dirs) or "  (목록 없음)"
    if corpus:
        hist_lines = []
        for c in corpus[-8:]:  # 최근 8개
            if c.failed:
                hist_lines.append(
                    f"  - {c.recipe_id} [실패]: {c.code_summary} → error: {c.error}"
                )
            else:
                hist_lines.append(
                    f"  - {c.recipe_id} [성공]: {c.code_summary} → metrics: {c.metrics}"
                )
        hist_block = "\n".join(hist_lines)
    else:
        hist_block = "  (이전 시도 없음 — cold start)"
    return (
        "너는 자율 ML 연구 에이전트다. MVTec anomaly detection(이미지 단위 + 픽셀 단위 "
        "이상탐지)을 위한 train.py 전체를 작성한다. 먼저 웹검색으로 최신(2024-2025) "
        "anomaly detection 기법(PatchCore, EfficientAD, FastFlow, Dinomaly 등)을 조사하라.\n\n"
        f"intent: {intent}\n\n"
        f"데이터 루트(--data-root)에 있는 디렉토리:\n{dirs_block}\n"
        "데이터 형태(이미지 경로/라벨/ground_truth)는 train.py가 직접 탐색해서 파악한다.\n"
        "MVTec 구조: train/(정상만), test/(정상+불량 클래스별), ground_truth/(픽셀 마스크).\n\n"
        f"이전 시도 이력 (반복/실패 회피, 개선 방향 참고):\n{hist_block}\n\n"
        "## 계약 (반드시 준수)\n"
        "- argparse로 `--data-root` 인자를 받는다.\n"
        "- 학습/평가 후 stdout에 정확히 `@image_auroc=<float> @pixel_auroc=<float>`를 출력한다.\n"
        "- 데이터 로딩~모델~학습~AUROC 평가를 train.py 한 파일에 모두 포함한다.\n"
        "- CUDA 있으면 쓰고 없으면 CPU로 graceful.\n"
        "- 비정상적으로 긴 학습 금지 (epochs 적게, 빠른 수렴).\n\n"
        "## 출력 형식\n"
        "1) 최신 기법 조사 근거를 1-2문장.\n"
        "2) ```python ... ``` 블록에 train.py 전체.\n"
        '3) 마지막 줄에 `requirements: ["pkg1", "pkg2", ...]` (pip 설치할 의존성).\n'
    )


class CodeGenSynthesizer:
    """train.py 전체 코드 생성기. web_search + corpus 환류."""

    def __init__(self, *, llm: CodeGenLLM) -> None:
        self._llm = llm

    async def propose(
        self,
        *,
        data_dirs: list[str],
        intent: str,
        corpus: list[CodeAttempt],
    ) -> NextConfigProposal:
        prompt = _build_prompt(data_dirs, intent, corpus)
        try:
            text, sources = await self._llm.generate(prompt)
        except Exception as exc:  # noqa: BLE001 — RR6
            logger.warning(
                "codegen_llm_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return _degrade(corpus)

        code = _extract_code_block(text)
        if code is None:
            logger.warning("codegen_no_code_block")
            return _degrade(corpus)

        reqs = _extract_requirements(text)
        recipe_id = _infer_recipe_id(text, code)
        return NextConfigProposal(
            recipe_id=recipe_id,
            next_config={"requirements": reqs},
            reasoning=text.split("```")[0].strip()[:300],
            evidence_ids=[],
            sources=sources,
            generated_code=code,
            requirements=reqs,
        )


class OpenAIWebSearchCodeGenLLM:
    """CodeGenLLM 구현 — OpenAI Responses API web_search. (text, sources) 반환.

    긴 코드 생성이므로 gpt-4o. web_search url_citation을 출처로 추출.
    """

    def __init__(self, model: str = "gpt-4o") -> None:
        from openai import AsyncOpenAI

        from the_commons.settings import settings

        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY 미설정")
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = model

    async def generate(self, prompt: str) -> tuple[str, list[str]]:
        from the_commons.matchmaker.agentic_novelty import _extract_sources

        response = await self._client.responses.create(
            model=self._model,
            tools=[{"type": "web_search"}],
            input=prompt,
        )
        text = getattr(response, "output_text", "") or ""
        sources = _extract_sources(response)
        return text, sources


def _infer_recipe_id(text: str, code: str) -> str:
    """생성 코드/설명에서 대략적 recipe 이름 추출 (lineage 라벨용)."""
    for kw in ("patchcore", "efficientad", "fastflow", "dinomaly", "padim",
               "simplenet", "autoencoder", "reverse_distill", "cflow"):
        if kw in text.lower() or kw in code.lower():
            return f"mvtec-{kw}"
    return "mvtec-anomaly"


def _degrade(corpus: list[CodeAttempt]) -> NextConfigProposal:
    """LLM/파싱 실패 → 직전 성공 코드 재시도, 없으면 최소 stub."""
    for c in reversed(corpus):
        if not c.failed and c.full_code:
            return NextConfigProposal(
                recipe_id=c.recipe_id,
                next_config={},
                reasoning="fallback: LLM 실패 → 직전 성공 코드 재시도",
                generated_code=c.full_code,
                requirements=[],
            )
    return NextConfigProposal(
        recipe_id="mvtec-stub",
        next_config={},
        reasoning="fallback: LLM 실패 + corpus 없음 → 계약 준수 stub",
        generated_code=_STUB_CODE,
        requirements=[],
    )
