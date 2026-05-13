"""실제 PostgreSQL로 PostgresEvidenceStore CRUD 검증."""

from datetime import UTC, datetime

import psycopg
import pytest

from tests.integration.conftest import requires_db
from the_commons.library.content_hash import compute_content_hash
from the_commons.library.models import Evidence
from the_commons.library.store import (
    EvidenceAlreadyExistsError,
    PostgresEvidenceStore,
)

pytestmark = requires_db


def _record(
    *,
    evidence_id: str,
    tier: str = "real",
    metric: float = 0.85,
    intent_goal: str = "exploration",
) -> dict:
    rec = {
        "evidence_id": evidence_id,
        "tier": tier,
        "outreach_origin": "external",
        "intent": {
            "goal": intent_goal,
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
    if tier == "synthetic":
        rec["synthetic_source"] = {
            "source_model": "gemini-flash-2.5",
            "prompt_hash": "sha256:x",
            "generated_at": datetime.now(UTC).isoformat(),
            "verifier": None,
        }
    rec["attribution"]["content_hash"] = compute_content_hash(rec)
    return rec


async def test_insert_and_get_real_evidence(
    clean_db_conn: psycopg.AsyncConnection,
) -> None:
    """real evidence를 insert하고 같은 ID로 조회."""
    store = PostgresEvidenceStore(clean_db_conn)
    rec = _record(evidence_id="ev-it-1")
    evidence = Evidence.model_validate(rec)

    await store.insert(evidence)
    fetched = await store.get_by_id("ev-it-1")

    assert fetched is not None
    assert fetched.evidence_id == "ev-it-1"
    assert fetched.tier == "real"
    assert fetched.metrics["AUC"] == 0.85


async def test_duplicate_id_raises_already_exists(
    clean_db_conn: psycopg.AsyncConnection,
) -> None:
    """같은 evidence_id 두 번 insert는 UniqueViolation → EvidenceAlreadyExistsError."""
    store = PostgresEvidenceStore(clean_db_conn)
    rec = _record(evidence_id="ev-it-dup")
    ev = Evidence.model_validate(rec)
    await store.insert(ev)

    with pytest.raises(EvidenceAlreadyExistsError):
        await store.insert(ev)


async def test_synthetic_attribution_check_constraint(
    clean_db_conn: psycopg.AsyncConnection,
) -> None:
    """tier='synthetic' but synthetic_source=NULL은 DB CHECK constraint로 거부.

    application 레이어 (validate_attribution)가 먼저 거르지만, DB가 마지막 게이트.
    여기선 store를 직접 호출해 DB constraint 확인.
    """
    store = PostgresEvidenceStore(clean_db_conn)
    rec = _record(evidence_id="ev-it-syn", tier="synthetic")
    # Pydantic 통과 후 synthetic_source 강제 제거 (DB 단에서만 reject 되는지 확인)
    rec["synthetic_source"] = None
    rec["attribution"]["content_hash"] = compute_content_hash(rec)
    ev = Evidence.model_validate(rec)

    with pytest.raises(psycopg.errors.CheckViolation):
        await store.insert(ev)


async def test_list_active_synthetics_in_bucket(
    clean_db_conn: psycopg.AsyncConnection,
) -> None:
    """같은 bucket의 active synthetic만 반환."""
    store = PostgresEvidenceStore(clean_db_conn)

    # 같은 bucket의 synthetic 2건
    for i in range(2):
        rec = _record(evidence_id=f"ev-syn-{i}", tier="synthetic")
        await store.insert(Evidence.model_validate(rec))

    # 다른 bucket의 synthetic 1건 (다른 intent_goal)
    other = _record(
        evidence_id="ev-syn-other", tier="synthetic", intent_goal="sota_challenge"
    )
    await store.insert(Evidence.model_validate(other))

    active = await store.list_active_synthetics_in_bucket(
        modality="tabular", sample_count_band="10k-100k", intent_goal="exploration"
    )
    ids = {ev.evidence_id for ev in active}
    assert ids == {"ev-syn-0", "ev-syn-1"}


async def test_count_real_in_bucket(
    clean_db_conn: psycopg.AsyncConnection,
) -> None:
    """real_count 정확 계산."""
    store = PostgresEvidenceStore(clean_db_conn)

    for i in range(3):
        rec = _record(evidence_id=f"ev-real-{i}", tier="real")
        await store.insert(Evidence.model_validate(rec))

    syn = _record(evidence_id="ev-syn-1", tier="synthetic")
    await store.insert(Evidence.model_validate(syn))

    count = await store.count_real_in_bucket(
        modality="tabular", sample_count_band="10k-100k", intent_goal="exploration"
    )
    assert count == 3


async def test_mark_deprecated_hides_from_active_list(
    clean_db_conn: psycopg.AsyncConnection,
) -> None:
    """deprecated 플래그 ON 후 active list에서 빠짐 (record 자체는 보존)."""
    store = PostgresEvidenceStore(clean_db_conn)
    rec = _record(evidence_id="ev-syn-x", tier="synthetic")
    await store.insert(Evidence.model_validate(rec))

    await store.mark_deprecated("ev-syn-x", reason="test")

    active = await store.list_active_synthetics_in_bucket(
        modality="tabular", sample_count_band="10k-100k", intent_goal="exploration"
    )
    assert "ev-syn-x" not in {ev.evidence_id for ev in active}

    # 단 record 자체는 보존 (L1 immutable)
    fetched = await store.get_by_id("ev-syn-x")
    assert fetched is not None
