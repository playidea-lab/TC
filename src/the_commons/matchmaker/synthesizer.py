"""LLM 합성기 — exploit/explore 분기마다 next_config를 생성.

WithinRecipeSynthesizer: infogain rerank top recipe + 그 recipe의 evidence history
+ intent → recipe 안에서 다음 시도할 hyperparam을 LLM이 합성.

NoveltyRecipeSynthesizer: 전체 corpus의 recipe 분포 + intent → corpus 밖 novelty
recipe + base config을 LLM이 제안.

RR6 정합: LLM 예외/스키마 위반은 추천 중단 금지 → 안전한 fallback proposal 반환.
fallback은 마지막 best evidence config 또는 합리적 default 한 점.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@runtime_checkable
class SynthesisLLM(Protocol):
    """텍스트 LLM 인터페이스. PriorLLM과 시그니처 동일 — duck-typing으로 공유 가능."""

    async def complete(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class EvidenceSummary:
    """LLM 프롬프트에 직렬화되는 evidence의 최소 요약. Synthesizer는 Evidence
    모델에 직접 의존하지 않는다 — service.py가 변환 책임."""

    evidence_id: str
    config: dict[str, Any]
    metrics: dict[str, Any]


@dataclass(frozen=True)
class RecipeStats:
    """novelty 합성에 보여줄 corpus 분포. recipe당 한 줄 요약."""

    recipe_id: str
    tries: int
    best_metric: float | None
    metric_name: str  # "test_acc" 등 — LLM이 의미를 알 수 있게


@dataclass(frozen=True)
class NextConfigProposal:
    """Synthesizer의 출력. ComposedCandidate.next_config/recipe_id로 흐름 연결."""

    recipe_id: str
    next_config: dict[str, Any]
    reasoning: str
    evidence_ids: list[str] = field(default_factory=list)


# ---------- 공통 ----------


def _extract_json(text: str) -> dict | None:
    """LLM 응답에서 최외곽 JSON object 추출. 실패 시 None."""
    # greedy로 첫 { ... } 매칭 — nested 객체 일부 지원 (dotall)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _validate_proposal_dict(obj: dict) -> tuple[str, dict, str] | None:
    """LLM 응답 dict에서 (recipe_id, next_config, reasoning) 검증·추출.

    스키마: {"recipe_id": str, "next_config": dict, "reasoning": str(optional)}.
    위반 시 None.
    """
    recipe_id = obj.get("recipe_id")
    next_config = obj.get("next_config")
    reasoning = obj.get("reasoning", "")
    if not isinstance(recipe_id, str) or not recipe_id:
        return None
    if not isinstance(next_config, dict) or not next_config:
        return None
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)
    return recipe_id, next_config, reasoning


# ---------- WithinRecipeSynthesizer ----------


def _build_within_prompt(
    recipe_id: str, evidences: list[EvidenceSummary], intent: str
) -> str:
    """recipe 안 evidence history + intent를 prompt에 직렬화.

    이미 시도한 distinct config를 '제외 대상'으로 명시해 LLM이 같은 config를 반복
    제안하는 정체(중복 자기복제)를 막는다.
    """
    history_lines = [
        f"- {ev.evidence_id}: config={json.dumps(ev.config, ensure_ascii=False)} "
        f"metrics={json.dumps(ev.metrics, ensure_ascii=False)}"
        for ev in evidences
    ]
    history = "\n".join(history_lines) if history_lines else "(없음)"
    tried_block = "\n".join(
        f"- {c}" for c in _distinct_config_strs(evidences)
    ) or "(없음)"
    return (
        "ML 실험 recipe 안에서 다음에 시도할 hyperparam을 합성한다.\n"
        f"recipe_id: {recipe_id}\n"
        f"intent: {intent}\n"
        f"history:\n{history}\n\n"
        f"이미 시도한 config (반드시 이것들과 다른 값 제안):\n{tried_block}\n\n"
        "next_config는 위 '이미 시도한 config' 중 어느 것과도 동일하면 안 된다. "
        "history의 metrics 추세를 보고 미탐색 hyperparam 영역을 제안하라.\n"
        'JSON만 출력: {"recipe_id": "<같은 recipe_id>", '
        '"next_config": {<hyperparams>}, "reasoning": "<짧은 근거>"}'
    )


def _distinct_config_strs(evidences: list[EvidenceSummary]) -> list[str]:
    """evidences의 distinct config를 정렬된 JSON 문자열 목록으로 (중복 제거)."""
    seen: set[str] = set()
    out: list[str] = []
    for ev in evidences:
        s = json.dumps(ev.config, sort_keys=True, ensure_ascii=False)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


class WithinRecipeSynthesizer:
    """exploit 분기 — 한 recipe 안에서 다음 config 합성."""

    def __init__(self, *, llm: SynthesisLLM) -> None:
        self._llm = llm

    async def propose(
        self, *, recipe_id: str, evidences: list[EvidenceSummary], intent: str
    ) -> NextConfigProposal:
        evidence_ids = [ev.evidence_id for ev in evidences]
        prompt = _build_within_prompt(recipe_id, evidences, intent)

        try:
            text = await self._llm.complete(prompt)
        except Exception as exc:  # noqa: BLE001 — RR6
            logger.warning(
                "within_recipe_llm_failed",
                recipe_id=recipe_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return _within_fallback(recipe_id, evidences, evidence_ids)

        obj = _extract_json(text)
        if obj is None:
            logger.warning("within_recipe_unparseable", recipe_id=recipe_id)
            return _within_fallback(recipe_id, evidences, evidence_ids)

        validated = _validate_proposal_dict(obj)
        if validated is None:
            logger.warning("within_recipe_schema_violation", recipe_id=recipe_id)
            return _within_fallback(recipe_id, evidences, evidence_ids)

        # LLM이 recipe_id를 바꿔도 우리는 within 분기 — 같은 recipe로 강제.
        _, next_config, reasoning = validated
        # 도서관 조회 가드: LLM이 이미 시도한 config를 그대로 반복하면(temp=0 정체)
        # lr을 미탐색 영역으로 밀어 탐색을 강제한다.
        next_config, reasoning = _avoid_tried_config(
            next_config, reasoning, evidences
        )
        return NextConfigProposal(
            recipe_id=recipe_id,
            next_config=next_config,
            reasoning=reasoning,
            evidence_ids=evidence_ids,
        )


# explore 강제 시 lr 확장 배수 + 상한 (발산 방지)
_PERTURB_FACTOR = 1.7
_LR_MAX = 0.5
_LR_KEYS = ("lr", "learning_rate")  # recipe마다 lr 키 이름이 다름


def _lr_field(cfg: dict[str, Any]) -> tuple[str | None, float | None]:
    """config에서 lr 계열 키와 값 추출 (lr / learning_rate)."""
    for k in _LR_KEYS:
        v = cfg.get(k)
        if isinstance(v, int | float):
            return k, float(v)
    return None, None


def _avoid_tried_config(
    next_config: dict[str, Any],
    reasoning: str,
    evidences: list[EvidenceSummary],
) -> tuple[dict[str, Any], str]:
    """next_config의 lr이 이미 시도한 lr이면 미탐색 영역으로 밀어 정체를 깬다.

    중복 판정은 lr 값 기준 — 같은 recipe 안에서 같은 lr 반복이 within 분기 자기복제
    정체의 본질이다. 전체 dict 비교는 키 미세 차이로 빗나가므로 lr에 집중한다.
    중복이 아니면 원본 그대로.
    """
    lr_key, cur_lr = _lr_field(next_config)
    tried_lrs = [
        v for ev in evidences if (v := _lr_field(ev.config)[1]) is not None
    ]
    if lr_key is None or cur_lr is None or not tried_lrs:
        return next_config, reasoning  # lr 없음 — perturbation 불가

    if not any(math.isclose(cur_lr, t, rel_tol=1e-6) for t in tried_lrs):
        return next_config, reasoning  # 미탐색 lr — 그대로

    # 중복 lr → 미탐색 영역으로. 상단 확장이 상한에 막히면 하단 축소.
    new_lr = min(max(tried_lrs) * _PERTURB_FACTOR, _LR_MAX)
    if any(math.isclose(new_lr, t, rel_tol=1e-6) for t in tried_lrs) or math.isclose(
        new_lr, cur_lr, rel_tol=1e-6
    ):
        new_lr = min(tried_lrs) / _PERTURB_FACTOR
    perturbed = dict(next_config)
    perturbed[lr_key] = new_lr
    return (
        perturbed,
        f"{reasoning} [guard: 중복 lr → {lr_key} 탐색 perturbation {cur_lr}→{new_lr}]",
    )


def _within_fallback(
    recipe_id: str,
    evidences: list[EvidenceSummary],
    evidence_ids: list[str],
) -> NextConfigProposal:
    """LLM 실패 시 fallback — 마지막 evidence의 config를 재시도, 없으면 빈 dict 회피."""
    if evidences:
        last_config = dict(evidences[-1].config)
    else:
        last_config = {"lr": 0.01, "batch_size": 128, "epochs": 1}
    return NextConfigProposal(
        recipe_id=recipe_id,
        next_config=last_config,
        reasoning="fallback: LLM 실패 또는 schema 위반 → 마지막 evidence config 재시도",
        evidence_ids=evidence_ids,
    )


# ---------- NoveltyRecipeSynthesizer ----------


def _build_novelty_prompt(corpus: list[RecipeStats], intent: str) -> str:
    """corpus 분포 + intent를 prompt에 직렬화."""
    if corpus:
        recipe_lines = [
            f"- {r.recipe_id}: tries={r.tries} best_{r.metric_name}={r.best_metric}"
            for r in corpus
        ]
        recipe_block = "\n".join(recipe_lines)
    else:
        recipe_block = "(corpus 비어있음)"
    return (
        "ML 실험 corpus 분포를 보고 아직 시도되지 않은 novelty recipe + 그 recipe의 "
        "base config를 제안한다.\n"
        f"intent: {intent}\n"
        f"existing recipes:\n{recipe_block}\n\n"
        "위 recipe들과 충분히 다른 새 recipe를 제안한다. existing recipe와 동일한 "
        "recipe_id는 피한다.\n"
        'JSON만 출력: {"recipe_id": "<새 recipe>", '
        '"next_config": {<hyperparams>}, "reasoning": "<왜 이 recipe>"}'
    )


class NoveltyRecipeSynthesizer:
    """explore 분기 — corpus 밖 새 recipe 합성."""

    def __init__(self, *, llm: SynthesisLLM) -> None:
        self._llm = llm

    async def propose(
        self, *, corpus_recipes: list[RecipeStats], intent: str
    ) -> NextConfigProposal:
        prompt = _build_novelty_prompt(corpus_recipes, intent)

        try:
            text = await self._llm.complete(prompt)
        except Exception as exc:  # noqa: BLE001 — RR6
            logger.warning(
                "novelty_recipe_llm_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return _novelty_fallback(corpus_recipes)

        obj = _extract_json(text)
        if obj is None:
            logger.warning("novelty_recipe_unparseable")
            return _novelty_fallback(corpus_recipes)

        validated = _validate_proposal_dict(obj)
        if validated is None:
            logger.warning("novelty_recipe_schema_violation")
            return _novelty_fallback(corpus_recipes)

        recipe_id, next_config, reasoning = validated
        return NextConfigProposal(
            recipe_id=recipe_id,
            next_config=next_config,
            reasoning=reasoning,
            evidence_ids=[],  # novelty는 backing evidence 없음
        )


def _novelty_fallback(corpus: list[RecipeStats]) -> NextConfigProposal:
    """fallback novelty recipe — corpus에 있는 recipe_id와 안 겹치는 stub."""
    used = {r.recipe_id for r in corpus}
    candidate = "experiment-explore-stub"
    if candidate in used:
        candidate = f"{candidate}-2"
    return NextConfigProposal(
        recipe_id=candidate,
        next_config={"lr": 0.01, "batch_size": 128, "epochs": 1},
        reasoning="fallback: LLM 실패 또는 schema 위반 → safe novelty stub",
        evidence_ids=[],
    )
