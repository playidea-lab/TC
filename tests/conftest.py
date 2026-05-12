"""pytest 공용 fixture."""

import pytest
from fastapi.testclient import TestClient

from the_commons.main import app


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient — sync 요청용."""
    return TestClient(app)
