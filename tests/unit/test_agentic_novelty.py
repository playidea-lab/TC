"""AgenticNoveltySynthesizer 단위 테스트 — degrade 경로 중심.

실제 grounding 호출은 통합 검증(사람-주도)에서. 본 테스트는 RR6 degrade:
grounding/agent 실패 시 주입된 단발 NoveltyRecipeSynthesizer로 떨어지는지 검증.
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


class _ExplodingModels:
    """models.generate_content가 항상 예외 — Gemini grounding 장애 모사."""

    def generate_content(self, **kwargs):  # noqa: ANN003, ANN201
        raise RuntimeError("grounding down")


class _ExplodingClient:
    """genai.Client stub — models가 폭발한다 (실제 Client.models는 setter 없는 property)."""

    def __init__(self) -> None:
        self.models = _ExplodingModels()


def _agent_with_broken_search() -> AgenticNoveltySynthesizer:
    fallback = NoveltyRecipeSynthesizer(llm=_StubFallbackLLM())
    agent = AgenticNoveltySynthesizer(fallback=fallback)
    # 내부 client를 폭발하는 stub으로 교체 (Client.models는 property라 통째 교체)
    agent._client = _ExplodingClient()  # type: ignore[assignment]
    return agent


@pytest.mark.asyncio
async def test_agentic_degrades_to_single_shot_on_search_failure() -> None:
    """grounding 실패 시 단발 NoveltyRecipeSynthesizer로 degrade (RR6)."""
    agent = _agent_with_broken_search()
    corpus = [RecipeStats(recipe_id="mnist-tinymlp", tries=5, best_metric=0.96, metric_name="test_acc")]
    p = await agent.propose(corpus_recipes=corpus, intent="acc 올리기")
    # fallback 응답이 와야
    assert p.recipe_id == "fallback-recipe"
    assert p.next_config["lr"] == 0.01
    assert p.sources == []  # 단발은 출처 없음


def test_extract_sources_handles_missing_candidates() -> None:
    """candidates 없는 응답에서도 빈 리스트로 안전 처리."""

    class _Resp:
        candidates = []

    assert _extract_sources(_Resp()) == []


def test_extract_sources_pulls_grounding_uris() -> None:
    """grounding_metadata.grounding_chunks[].web.uri에서 URL 추출."""

    class _Web:
        uri = "https://example.com/paper"

    class _Chunk:
        web = _Web()

    class _GroundingMeta:
        grounding_chunks = [_Chunk()]

    class _Cand:
        grounding_metadata = _GroundingMeta()

    class _Resp:
        candidates = [_Cand()]

    assert _extract_sources(_Resp()) == ["https://example.com/paper"]
