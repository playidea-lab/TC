"""저데이터 regime LLM Beta prior 공급 (ID3) + RR6 graceful degrade.

retrieved 이웃에 특정 recipe의 real evidence가 희소하면 Beta 사후가 prior
그대로라 엔트로피 추정이 불안정하다. 이때 LLM이 world knowledge로 informed
prior(α₀,β₀)를 공급한다. real evidence가 임계 이상이면 likelihood가 이미
우세하므로 LLM을 호출하지 않는다(=synthetic auto-retire의 수학적 쌍대, ID4).

임계는 settings.retirement_real_threshold를 재사용한다 (새 상수 신설 금지 —
synthetic-tier retire와 같은 임계 철학 공유).

RR6: LLM 예외·파싱 실패는 추천을 절대 중단시키지 않는다 — weak uniform
prior로 degrade하고 warning만 남긴다.
"""

from __future__ import annotations

import json
import re
from typing import Protocol, runtime_checkable

import structlog

from the_commons.settings import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# weak uniform prior — likelihood가 곧 압도 (synthetic seed의 retire 쌍대)
WEAK_DEFAULT_PRIOR: tuple[float, float] = (1.0, 1.0)

# 과신 방지 클램프 — prior는 약해야 real 관측이 빨리 이긴다
_MIN_PARAM = 0.1
_MAX_PARAM = 10.0


@runtime_checkable
class PriorLLM(Protocol):
    """prior 추출용 최소 텍스트 생성 인터페이스 (vendor 중립)."""

    async def complete(self, prompt: str) -> str:
        """프롬프트에 대한 텍스트 응답."""
        ...


def _clamp(value: float) -> float:
    return max(_MIN_PARAM, min(_MAX_PARAM, value))


def _parse_prior(text: str) -> tuple[float, float] | None:
    """LLM 응답에서 (alpha, beta) 추출. 실패 시 None."""
    # 1차: JSON object
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            a = float(obj["alpha"])
            b = float(obj["beta"])
            if a > 0.0 and b > 0.0:
                return _clamp(a), _clamp(b)
        except (ValueError, KeyError, TypeError):
            pass
    return None


def _build_prompt(recipe_id: str, sparse_context: str) -> str:
    return (
        "ML 실험 recipe의 성공 가능성에 대한 약한 사전분포를 Beta(alpha,beta)로 "
        "추정한다. 확신하지 말고 넓은 분산(작은 alpha+beta)을 유지하라.\n"
        f"recipe: {recipe_id}\n"
        f"context: {sparse_context}\n"
        'JSON만 출력: {"alpha": <float>, "beta": <float>}'
    )


async def llm_beta_prior(
    recipe_id: str,
    sparse_context: str,
    *,
    real_count: int,
    llm: PriorLLM,
) -> tuple[float, float]:
    """저데이터 recipe에 LLM informed Beta prior. 아니면/실패 시 weak default.

    real_count >= settings.retirement_real_threshold → LLM 미호출, (1,1).
    LLM 예외·파싱 실패 → (1,1) + warning (RR6, 추천 중단 금지).
    """
    if real_count >= settings.retirement_real_threshold:
        # likelihood 우세 regime — LLM prior 불필요
        return WEAK_DEFAULT_PRIOR

    try:
        text = await llm.complete(_build_prompt(recipe_id, sparse_context))
    except Exception as exc:  # noqa: BLE001 — RR6: 어떤 LLM 장애도 중단 금지
        logger.warning(
            "llm_prior_call_failed",
            recipe_id=recipe_id,
            error=str(exc),
            error_type=type(exc).__name__,
            fallback="weak_default_prior",
        )
        return WEAK_DEFAULT_PRIOR

    parsed = _parse_prior(text)
    if parsed is None:
        logger.warning(
            "llm_prior_unparseable",
            recipe_id=recipe_id,
            fallback="weak_default_prior",
        )
        return WEAK_DEFAULT_PRIOR
    return parsed


def _build_batch_prompt(recipe_ids: list[str], sparse_context: str) -> str:
    """N개 recipe의 Beta prior를 1회 호출로 요청 (직렬 N회 → 1회)."""
    listed = "\n".join(f"- {r}" for r in recipe_ids)
    return (
        "여러 ML 실험 recipe 각각의 성공 가능성에 대한 약한 사전분포를 "
        "Beta(alpha,beta)로 추정한다. 확신하지 말고 넓은 분산(작은 alpha+beta)을 "
        "유지하라.\n"
        f"context: {sparse_context}\n"
        f"recipes:\n{listed}\n"
        'JSON만 출력 (recipe_id를 key로): '
        '{"<recipe_id>": {"alpha": <float>, "beta": <float>}, ...}'
    )


def _parse_batch_prior(
    text: str, recipe_ids: list[str]
) -> dict[str, tuple[float, float]]:
    """LLM 응답에서 recipe별 (alpha,beta) 추출. 누락·오류 recipe는 결과에서 제외."""
    out: dict[str, tuple[float, float]] = {}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return out
    try:
        obj = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return out
    if not isinstance(obj, dict):
        return out
    for rid in recipe_ids:
        entry = obj.get(rid)
        if not isinstance(entry, dict):
            continue
        try:
            a = float(entry["alpha"])
            b = float(entry["beta"])
        except (KeyError, ValueError, TypeError):
            continue
        if a > 0.0 and b > 0.0:
            out[rid] = (_clamp(a), _clamp(b))
    return out


async def llm_beta_priors_batch(
    recipe_ids: list[str],
    sparse_context: str,
    *,
    llm: PriorLLM,
) -> dict[str, tuple[float, float]]:
    """저데이터 recipe들의 Beta prior를 1회 LLM 호출로 일괄 추출 (직렬 N회 회피).

    real_count 필터는 호출부(reranker) 책임 — 여기엔 저데이터 recipe만 들어온다.
    누락·실패 recipe는 결과 dict에서 빠지고, 호출부가 WEAK_DEFAULT_PRIOR로 채운다.
    빈 입력·LLM 예외·파싱 실패는 빈 dict로 degrade (RR6, 추천 중단 금지).
    """
    if not recipe_ids:
        return {}
    try:
        text = await llm.complete(_build_batch_prompt(recipe_ids, sparse_context))
    except Exception as exc:  # noqa: BLE001 — RR6: 어떤 LLM 장애도 중단 금지
        logger.warning(
            "llm_batch_prior_call_failed",
            recipe_count=len(recipe_ids),
            error=str(exc),
            error_type=type(exc).__name__,
            fallback="weak_default_prior",
        )
        return {}
    parsed = _parse_batch_prior(text, recipe_ids)
    if len(parsed) < len(recipe_ids):
        logger.warning(
            "llm_batch_prior_partial",
            requested=len(recipe_ids),
            parsed=len(parsed),
            fallback="weak_default_for_missing",
        )
    return parsed
