"""AgenticNoveltySynthesizer — 웹검색을 활용하는 explore 분기 합성기.

idea: `.cq/runtime/ideas/cq-tc-agentic-novelty-websearch.md`

단발 NoveltyRecipeSynthesizer가 LLM training cutoff에 갇히는 한계를 넘어, OpenAI
Responses API의 web_search 빌트인 tool로 최신 기법·SOTA를 실시간 조사한 뒤 corpus
밖 novelty recipe를 합성한다. NoveltyRecipeSynthesizer와 동일 propose 시그니처라
DI 교체만으로 ε-novelty mix의 explore 분기를 대체한다.

RR6 정합: web_search·agent·파싱 실패는 추천을 중단시키지 않고 주입된 단발
NoveltyRecipeSynthesizer(fallback)로 degrade한다.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from openai import AsyncOpenAI

from the_commons.llm.cost_meter import meter
from the_commons.matchmaker.synthesizer import (
    NextConfigProposal,
    NoveltyRecipeSynthesizer,
    RecipeStats,
    _extract_json,
    _validate_proposal_dict,
)
from the_commons.settings import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# web_search agent 모델 — gpt-4o 계열이 Responses API web_search tool 지원
_DEFAULT_AGENT_MODEL = "gpt-4o"


def _build_agent_prompt(corpus: list[RecipeStats], intent: str) -> str:
    """웹검색 agent용 프롬프트 — 최신 기법 조사 + corpus 밖 novelty 합성 지시."""
    if corpus:
        recipe_lines = [
            f"- {r.recipe_id}: tries={r.tries} best_{r.metric_name}={r.best_metric}"
            for r in corpus
        ]
        recipe_block = "\n".join(recipe_lines)
    else:
        recipe_block = "(corpus 비어있음 — cold start)"
    return (
        "너는 ML 실험 소믈리에다. 웹검색으로 이 intent·데이터셋에 대한 최신(2024-2025) "
        "기법·SOTA·권장 hyperparameter를 조사한 뒤, 아래 corpus가 아직 시도하지 않은 "
        "novelty recipe를 제안한다.\n\n"
        f"intent: {intent}\n"
        f"이미 corpus에 있는 recipe (피할 것):\n{recipe_block}\n\n"
        "먼저 웹검색으로 최신 기법을 조사하고, 그 근거를 바탕으로 corpus 밖 새 recipe와 "
        "합리적 hyperparameter(과도하게 작은 lr 금지)를 제안한다.\n"
        "마지막 줄에 JSON만 출력: "
        '{"recipe_id": "<새 recipe>", "next_config": {<hyperparams>}, '
        '"reasoning": "<왜 이 recipe, 어떤 최신 근거>"}'
    )


def _extract_sources(response: Any) -> list[str]:
    """Responses API 응답에서 web_search url_citation 출처 추출 (best-effort)."""
    sources: list[str] = []
    try:
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) != "message":
                continue
            for content in getattr(item, "content", []) or []:
                for ann in getattr(content, "annotations", []) or []:
                    url = getattr(ann, "url", None)
                    if isinstance(url, str) and url and url not in sources:
                        sources.append(url)
    except Exception:  # noqa: BLE001 — 출처 추출 실패가 추천을 막지 않게
        return sources
    return sources


class AgenticNoveltySynthesizer:
    """explore 분기 — 웹검색 agent로 최신 기법 조사 후 novelty recipe 합성.

    fallback은 단발 NoveltyRecipeSynthesizer — web_search/agent 실패 시 degrade.
    """

    def __init__(
        self,
        *,
        fallback: NoveltyRecipeSynthesizer,
        model: str | None = None,
    ) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY 미설정")
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = model or _DEFAULT_AGENT_MODEL
        self._fallback = fallback

    async def propose(
        self, *, corpus_recipes: list[RecipeStats], intent: str
    ) -> NextConfigProposal:
        prompt = _build_agent_prompt(corpus_recipes, intent)

        try:
            response = await self._client.responses.create(
                model=self._model,
                tools=[{"type": "web_search"}],
                input=prompt,
            )
        except Exception as exc:  # noqa: BLE001 — RR6: 단발 novelty로 degrade
            logger.warning(
                "agentic_novelty_search_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                fallback="single_shot_novelty",
            )
            return await self._fallback.propose(
                corpus_recipes=corpus_recipes, intent=intent
            )

        text = getattr(response, "output_text", "") or ""
        sources = _extract_sources(response)
        _meter_usage(response, self._model)

        obj = _extract_json(text)
        validated = _validate_proposal_dict(obj) if obj else None
        if validated is None:
            logger.warning(
                "agentic_novelty_unparseable", fallback="single_shot_novelty"
            )
            return await self._fallback.propose(
                corpus_recipes=corpus_recipes, intent=intent
            )

        recipe_id, next_config, reasoning = validated
        web_note = f" [web: {len(sources)} sources]" if sources else " [web: 0 sources]"
        return NextConfigProposal(
            recipe_id=recipe_id,
            next_config=next_config,
            reasoning=reasoning + web_note,
            evidence_ids=[],
            sources=sources,
        )


def _meter_usage(response: Any, model: str) -> None:
    """Responses API usage를 cost_meter에 보고 (best-effort)."""
    try:
        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        meter.record(
            model=model, operation="agentic_novelty", input_tokens=in_tok, output_tokens=out_tok
        )
    except Exception:  # noqa: BLE001
        return
