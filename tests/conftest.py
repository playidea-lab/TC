"""pytest 공용 fixture + 전역 격리 처리."""

import pytest
from fastapi.testclient import TestClient

from the_commons.api import dependencies as api_dependencies
from the_commons.api.dependencies import get_embedder
from the_commons.api.rate_limit import ingest_bucket, recommend_bucket
from the_commons.llm.cost_meter import meter
from the_commons.main import app
from the_commons.reciprocity.event_store import InMemoryReciprocityEventStore


class _DefaultFakeEmbedder:
    """결정론적 fake embedder — 단위 테스트가 실제 Gemini(GOOGLE_API_KEY)에
    의존하지 않도록 기본 주입한다. 특정 벡터가 필요한 테스트는 자체
    dependency_overrides로 교체하면 그쪽이 우선한다."""

    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


async def _default_embedder() -> _DefaultFakeEmbedder:
    return _DefaultFakeEmbedder()


@pytest.fixture(autouse=True)
def _reset_module_singletons():
    """매 test 시작 시 module-level state 초기화.

    A.13 — rate-limit bucket, cost meter
    F.3 — api.dependencies._inmemory_reciprocity (Postgres 없는 환경의 fallback)
    embedder — 키 없는 환경에서 실제 Gemini 호출을 막기 위한 기본 fake 주입
    """
    recommend_bucket.reset()
    ingest_bucket.reset()
    meter.reset()
    # F.3 — _inmemory_reciprocity가 test 간 누적되면 verdict / find_verifier_for가
    # 이전 test 영향 받음. 매 test 새 instance로 교체.
    api_dependencies._inmemory_reciprocity = InMemoryReciprocityEventStore()
    # 단위 테스트는 외부 LLM에 의존하면 안 된다. 자체 override가 없는 테스트를 위해
    # 기본 fake embedder를 주입한다. (자체 override는 dict에 덮어써져 우선 적용)
    app.dependency_overrides[get_embedder] = _default_embedder
    yield
    app.dependency_overrides.pop(get_embedder, None)


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient — sync 요청용."""
    return TestClient(app)
