"""pytest 공용 fixture + 전역 격리 처리."""

import pytest
from fastapi.testclient import TestClient

from the_commons.api.rate_limit import ingest_bucket, recommend_bucket
from the_commons.llm.cost_meter import meter
from the_commons.main import app


@pytest.fixture(autouse=True)
def _reset_module_singletons() -> None:
    """A.13 — module-level singleton(rate-limit bucket, cost meter)을
    매 test 시작 시 reset. test 실행 순서에 fragile했던 부분 회복."""
    recommend_bucket.reset()
    ingest_bucket.reset()
    meter.reset()


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient — sync 요청용."""
    return TestClient(app)
