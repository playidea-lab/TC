"""실제 pgvector cosine search 검증."""

from datetime import UTC, datetime

import psycopg
import pytest_asyncio

from tests.integration.conftest import requires_db
from the_commons.library.content_hash import compute_content_hash
from the_commons.library.models import Evidence
from the_commons.library.store import PostgresEvidenceStore
from the_commons.matchmaker.retriever import PgvectorVectorIndex

pytestmark = requires_db


VECTOR_DIM = 1024


def _record_with_vector_marker(
    *,
    evidence_id: str,
    metric: float,
) -> dict:
    rec = {
        "evidence_id": evidence_id,
        "tier": "real",
        "outreach_origin": "external",
        "intent": {
            "goal": "exploration",
            "expected_baseline": None,
            "tolerance": None,
        },
        "data_fingerprint": {
            "modality": "tabular",
            "sample_count_band": "10k-100k",
            "schema_summary": {},
            "statistical_moments": {},
        },
        "config": {"recipe_id": "lightgbm"},
        "metrics": {"AUC": metric},
        "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
        "attribution": {
            "contributor_id": None,
            "content_hash": "",
            "created_at": datetime.now(UTC).isoformat(),
            "pcq_version": "2.0.0",
        },
        "synthetic_source": None,
    }
    rec["attribution"]["content_hash"] = compute_content_hash(rec)
    return rec


@pytest_asyncio.fixture
async def seeded_index(clean_db_conn: psycopg.AsyncConnection):
    """3개 evidence를 다른 vector로 시드. pgvector type adapter 등록 후."""
    from pgvector.psycopg import register_vector_async

    await register_vector_async(clean_db_conn)
    store = PostgresEvidenceStore(clean_db_conn)

    # 3개 vector: 첫 번째는 query와 정확히 같은 방향, 나머지는 점점 멀어짐
    vectors = {
        "ev-near": [1.0] + [0.0] * (VECTOR_DIM - 1),
        "ev-mid": [0.7, 0.7] + [0.0] * (VECTOR_DIM - 2),
        "ev-far": [0.0] * (VECTOR_DIM - 1) + [1.0],
    }
    for eid, vec in vectors.items():
        rec = _record_with_vector_marker(evidence_id=eid, metric=0.85)
        await store.insert(Evidence.model_validate(rec))
        # 별도 UPDATE로 embedding 채움
        async with clean_db_conn.cursor() as cur:
            await cur.execute(
                "UPDATE evidence SET embedding = %s::vector WHERE evidence_id = %s",
                (vec, eid),
            )
    return clean_db_conn


async def test_cosine_search_returns_nearest_first(seeded_index) -> None:
    """query=[1,0,...]은 ev-near가 가장 가까움."""
    index = PgvectorVectorIndex(seeded_index)
    query_vec = [1.0] + [0.0] * (VECTOR_DIM - 1)
    hits = await index.search(query_vec, top_k=3)

    assert [h.evidence_id for h in hits] == ["ev-near", "ev-mid", "ev-far"]
    assert hits[0].similarity > hits[1].similarity > hits[2].similarity


async def test_cosine_search_respects_top_k(seeded_index) -> None:
    """top_k=2면 2개 반환."""
    index = PgvectorVectorIndex(seeded_index)
    query_vec = [1.0] + [0.0] * (VECTOR_DIM - 1)
    hits = await index.search(query_vec, top_k=2)
    assert len(hits) == 2


async def test_deprecated_evidence_excluded_from_search(
    seeded_index, clean_db_conn: psycopg.AsyncConnection
) -> None:
    """deprecated=TRUE인 evidence는 retrieve에서 제외 (partial index 조건)."""
    # ev-near를 deprecated 처리
    async with clean_db_conn.cursor() as cur:
        await cur.execute(
            "UPDATE evidence SET deprecated = TRUE, deprecated_reason = 'test' "
            "WHERE evidence_id = 'ev-near'"
        )

    index = PgvectorVectorIndex(seeded_index)
    query_vec = [1.0] + [0.0] * (VECTOR_DIM - 1)
    hits = await index.search(query_vec, top_k=10)

    ids = [h.evidence_id for h in hits]
    assert "ev-near" not in ids
    assert "ev-mid" in ids
