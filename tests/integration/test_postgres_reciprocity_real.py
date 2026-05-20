"""실제 PostgreSQL로 PostgresReciprocityEventStore SQL 동작 검증.

A.2 (review): InMemory에선 list 순회로 검증 가능하지만 jsonb @> containment의
PostgreSQL 동작은 실 DB에서 확인해야 한다.

reciprocity_event.primary_evidence_id는 evidence FK이므로 test마다 evidence를
먼저 시드한다.
"""

from datetime import UTC, datetime

import psycopg

from tests.integration.conftest import requires_db
from the_commons.library.content_hash import compute_content_hash
from the_commons.library.models import Evidence
from the_commons.library.store import PostgresEvidenceStore
from the_commons.reciprocity.event_store import PostgresReciprocityEventStore

pytestmark = requires_db


def _record(evidence_id: str, *, tier: str = "real") -> dict:
    """pcq 2.x envelope 형식."""
    pcq_record = {
        "intent": {"goal": "exploration", "expected_baseline": None, "tolerance": None},
        "data_fingerprint": {
            "modality": "tabular",
            "sample_count_band": "10k-100k",
            "schema_summary": {},
            "statistical_moments": {},
        },
        "config": {"recipe_id": "lightgbm"},
        "metrics": {"AUC": 0.85},
        "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
        "attribution": {"operator": None, "signature": None},
        "contract_version": "2.0",
    }
    pcq_record["attribution"]["content_hash"] = compute_content_hash(pcq_record)
    envelope = {
        "evidence_id": evidence_id,
        "tier": tier,
        "outreach_origin": "external",
        "synthetic_source": None,
        "pcq_record": pcq_record,
    }
    if tier == "synthetic":
        envelope["synthetic_source"] = {
            "source_model": "gemini-2.5-flash",
            "prompt_hash": "sha256:x",
            "generated_at": datetime.now(UTC).isoformat(),
            "verifier": None,
        }
    return envelope


async def _seed(
    ev_store: PostgresEvidenceStore, *, ids_and_tiers: list[tuple[str, str]]
) -> None:
    """헬퍼: 여러 evidence를 한 번에 insert."""
    for eid, tier in ids_and_tiers:
        await ev_store.insert(Evidence.model_validate(_record(eid, tier=tier)))


async def test_record_and_count_by_type(
    clean_db_conn: psycopg.AsyncConnection,
) -> None:
    """record → count_by_type round-trip."""
    ev_store = PostgresEvidenceStore(clean_db_conn)
    rcp_store = PostgresReciprocityEventStore(clean_db_conn)

    await _seed(ev_store, ids_and_tiers=[("ev-a", "real"), ("ev-real", "real")])

    await rcp_store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-a",
        related_evidence_ids=[],
        origin="external",
    )
    await rcp_store.record(
        event_type="promote",
        primary_evidence_id="ev-real",
        related_evidence_ids=["ev-syn-1"],
        origin="external",
    )

    counts = await rcp_store.count_by_type()
    assert counts["loop_closure"] == 1
    assert counts["promote"] == 1
    assert counts["contradicts"] == 0


async def test_find_verifier_for_returns_promote_primary(
    clean_db_conn: psycopg.AsyncConnection,
) -> None:
    """promote event 기록 후 find_verifier_for가 primary_evidence_id 반환.

    jsonb @> containment가 array element 매칭 정확히 작동하는지 검증.
    """
    ev_store = PostgresEvidenceStore(clean_db_conn)
    rcp_store = PostgresReciprocityEventStore(clean_db_conn)

    await _seed(
        ev_store,
        ids_and_tiers=[("ev-real-1", "real"), ("ev-syn-target", "synthetic")],
    )

    await rcp_store.record(
        event_type="promote",
        primary_evidence_id="ev-real-1",
        related_evidence_ids=["ev-syn-target"],
        origin="external",
    )

    verifier = await rcp_store.find_verifier_for("ev-syn-target")
    assert verifier == "ev-real-1"


async def test_find_verifier_for_returns_contradicts_primary(
    clean_db_conn: psycopg.AsyncConnection,
) -> None:
    """contradicts도 verifier로 간주."""
    ev_store = PostgresEvidenceStore(clean_db_conn)
    rcp_store = PostgresReciprocityEventStore(clean_db_conn)

    await _seed(
        ev_store,
        ids_and_tiers=[("ev-real-2", "real"), ("ev-syn-target", "synthetic")],
    )

    await rcp_store.record(
        event_type="contradicts",
        primary_evidence_id="ev-real-2",
        related_evidence_ids=["ev-syn-target"],
        origin="external",
    )

    assert await rcp_store.find_verifier_for("ev-syn-target") == "ev-real-2"


async def test_find_verifier_for_ignores_loop_closure_events(
    clean_db_conn: psycopg.AsyncConnection,
) -> None:
    """loop_closure event는 verifier 아님 (검증 행위가 아니라 인용만)."""
    ev_store = PostgresEvidenceStore(clean_db_conn)
    rcp_store = PostgresReciprocityEventStore(clean_db_conn)

    await _seed(
        ev_store,
        ids_and_tiers=[("ev-real-x", "real"), ("ev-syn-target", "synthetic")],
    )

    await rcp_store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-real-x",
        related_evidence_ids=["ev-syn-target"],
        origin="external",
    )

    assert await rcp_store.find_verifier_for("ev-syn-target") is None


async def test_find_verifier_for_ignores_unrelated_synthetic(
    clean_db_conn: psycopg.AsyncConnection,
) -> None:
    """다른 synthetic을 검증한 event는 영향 없음 — jsonb 정확 매칭."""
    ev_store = PostgresEvidenceStore(clean_db_conn)
    rcp_store = PostgresReciprocityEventStore(clean_db_conn)

    await _seed(
        ev_store,
        ids_and_tiers=[("ev-real-1", "real"), ("ev-syn-other", "synthetic")],
    )

    await rcp_store.record(
        event_type="promote",
        primary_evidence_id="ev-real-1",
        related_evidence_ids=["ev-syn-other"],
        origin="external",
    )

    assert await rcp_store.find_verifier_for("ev-syn-target") is None


async def test_find_verifier_for_picks_first_when_multiple_events(
    clean_db_conn: psycopg.AsyncConnection,
) -> None:
    """같은 synthetic을 여러 번 verify해도 ORDER BY created_at ASC LIMIT 1로 첫 결과."""
    ev_store = PostgresEvidenceStore(clean_db_conn)
    rcp_store = PostgresReciprocityEventStore(clean_db_conn)

    await _seed(
        ev_store,
        ids_and_tiers=[
            ("ev-real-first", "real"),
            ("ev-real-second", "real"),
            ("ev-syn-target", "synthetic"),
        ],
    )

    await rcp_store.record(
        event_type="promote",
        primary_evidence_id="ev-real-first",
        related_evidence_ids=["ev-syn-target"],
        origin="external",
    )
    await rcp_store.record(
        event_type="contradicts",
        primary_evidence_id="ev-real-second",
        related_evidence_ids=["ev-syn-target"],
        origin="external",
    )

    verifier = await rcp_store.find_verifier_for("ev-syn-target")
    assert verifier == "ev-real-first"


async def test_count_by_origin_omits_unused_then_verdict_fills_defaults(
    clean_db_conn: psycopg.AsyncConnection,
) -> None:
    """A.5 — Postgres GROUP BY가 internal 없으면 dict에 omit. verdict_report가 채움."""
    from the_commons.reciprocity.verdict_report import build_verdict_report

    ev_store = PostgresEvidenceStore(clean_db_conn)
    rcp_store = PostgresReciprocityEventStore(clean_db_conn)

    await _seed(ev_store, ids_and_tiers=[("ev-a", "real")])

    await rcp_store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-a",
        related_evidence_ids=[],
        origin="external",
    )

    raw = await rcp_store.count_by_origin()
    assert "external" in raw
    assert "internal" not in raw

    report = await build_verdict_report(rcp_store)
    assert report.counts_by_origin["internal"] == 0
    assert report.counts_by_origin["external"] == 1
