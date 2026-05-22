"""AgenticNoveltySynthesizer 단위 테스트 — degrade 경로 중심.

실제 web_search 호출은 통합 검증(사람-주도)에서. 본 테스트는 RR6 degrade:
web_search/agent 실패 시 주입된 단발 NoveltyRecipeSynthesizer로 떨어지는지 검증.
"""

from __future__ import annotations

import pytest

from the_commons.matchmaker.agentic_novelty import AgenticNoveltySynthesizer, _extract_sources
from the_commons.matchmaker.synthesizer import NoveltyRecipeSynthesizer, RecipeStats


class _StubFallbackLLM:
    """단발 fallback novelty용 LLM stub."""

    async def complete(self, prompt: str) -> str:
        return (
            '{"recipe_id": "fallback-recipe", '
            '"next_config": {"lr": 0.01}, "reasoning": "단발 fallback"}'
        )


class _ExplodingResponses:
    """responses.create가 항상 예외 — web_search 장애 모사."""

    async def create(self, **kwargs):  # noqa: ANN003, ANN201
        raise RuntimeError("web_search down")


def _agent_with_broken_search() -> AgenticNoveltySynthesizer:
    fallback = NoveltyRecipeSynthesizer(llm=_StubFallbackLLM())
    agent = AgenticNoveltySynthesizer(fallback=fallback)
    # 내부 client.responses를 폭발하는 stub으로 교체
    agent._client.responses = _ExplodingResponses()  # type: ignore[attr-defined]
    return agent


@pytest.mark.asyncio
async def test_agentic_degrades_to_single_shot_on_search_failure() -> None:
    """web_search 실패 시 단발 NoveltyRecipeSynthesizer로 degrade (RR6)."""
    agent = _agent_with_broken_search()
    corpus = [RecipeStats(recipe_id="mnist-tinymlp", tries=5, best_metric=0.96, metric_name="test_acc")]
    p = await agent.propose(corpus_recipes=corpus, intent="acc 올리기")
    # fallback 응답이 와야
    assert p.recipe_id == "fallback-recipe"
    assert p.next_config["lr"] == 0.01
    assert p.sources == []  # 단발은 출처 없음


def test_extract_sources_handles_missing_annotations() -> None:
    """annotations 없는 응답에서도 빈 리스트로 안전 처리."""

    class _Resp:
        output = []

    assert _extract_sources(_Resp()) == []


def test_extract_sources_pulls_url_citations() -> None:
    """url_citation annotation에서 URL 추출."""

    class _Ann:
        url = "https://example.com/paper"

    class _Content:
        annotations = [_Ann()]

    class _Item:
        type = "message"
        content = [_Content()]

    class _Resp:
        output = [_Item()]

    assert _extract_sources(_Resp()) == ["https://example.com/paper"]
