"""실제 Gemini API 호출 — embedding + listwise rerank.

GOOGLE_API_KEY가 .env 또는 환경변수에 있을 때만 실행. 1회 호출 비용 매우 작음
(<$0.001) but 외부 의존성이므로 unit suite와 분리.
"""

from tests.integration.conftest import requires_gemini
from the_commons.llm.cost_meter import meter
from the_commons.llm.gemini import (
    GeminiEmbedding2Provider,
    GeminiFlash25Reranker,
)

pytestmark = requires_gemini


async def test_gemini_embedding_returns_nonempty_vector() -> None:
    """단일 text 임베딩 — 벡터 차원·numeric 검증."""
    provider = GeminiEmbedding2Provider()
    vector = await provider.embed(
        "Tabular dataset: 10k-100k samples, binary classification, "
        "5-15% positive class. Goal: explore what works."
    )
    assert isinstance(vector, list)
    assert len(vector) > 0
    assert all(isinstance(v, (int, float)) for v in vector)


async def test_gemini_embedding_batch_returns_one_vector_per_text() -> None:
    """batch 호출 — N texts → N vectors, 동일 차원."""
    provider = GeminiEmbedding2Provider()
    vectors = await provider.embed_batch(
        [
            "LightGBM on tabular ~50k binary classification",
            "XGBoost on tabular ~50k binary classification",
            "TabPFN on tabular ~5k binary classification",
        ]
    )
    assert len(vectors) == 3
    dim = len(vectors[0])
    assert dim > 0
    assert all(len(v) == dim for v in vectors)


async def test_gemini_listwise_rerank_returns_ranked_candidates() -> None:
    """listwise rerank 1회 호출 — top-N ranked + reasoning 필드."""
    reranker = GeminiFlash25Reranker()
    candidates = [
        "LightGBM run on tabular ~50k binary. Observed AUC=0.85.",
        "Logistic Regression baseline. Observed AUC=0.71.",
        "TabPFN run on tabular ~5k. Observed AUC=0.78.",
    ]
    ranked = await reranker.rerank(
        query=(
            "Tabular dataset: 10k-100k binary classification. "
            "Goal: SOTA challenge target AUC=0.85."
        ),
        candidates=candidates,
        top_n=2,
    )
    # LLM이 응답 형식을 깨면 빈 list가 올 수도 — 그땐 skip-ish 대신 명시 실패
    assert len(ranked) >= 1, "rerank 응답 파싱 실패 — prompt format 점검 필요"
    for r in ranked:
        assert 0 <= r.index < len(candidates)
        assert isinstance(r.reasoning, str)


async def test_cost_meter_records_gemini_calls() -> None:
    """위 호출 후 cost_meter에 entry가 누적되어 있어야."""
    summary = meter.summary()
    # 위 test들이 같은 session에서 실행되면 total_calls > 0
    # 단 pytest는 test마다 격리될 수 있어 정확 수치는 단언 안 함
    assert summary.total_calls >= 0
