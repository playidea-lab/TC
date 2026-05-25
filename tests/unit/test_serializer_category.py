"""serialize_query/evidence가 category·intent description을 검색 텍스트에 반영하는지.

버그(2026-05 발견): serialize_query는 modality+band+goal만 직렬화해 카테고리(예: MVTec
bottle vs screw)를 구분 못했다 → 다른 카테고리 query의 임베딩이 동일 → retrieve가
카테고리 무관하게 검색. serialize_evidence도 config.category를 누락했다.
"""

from the_commons.library.models import Evidence
from the_commons.matchmaker.serializer.templates_v1 import (
    serialize_evidence,
    serialize_query,
)
from the_commons.matchmaker.serializer.types import QueryFeatures


def _query_with_description(desc: str) -> QueryFeatures:
    return QueryFeatures.model_validate(
        {
            "worker_spec": {"cpu_cores": 8, "ram_gb": 16, "has_gpu": False},
            "data_fingerprint": {"modality": "vision", "sample_count_band": "100-1k"},
            "intent": {
                "goal": "exploration",
                "description": desc,
                "expected_baseline": {"metric": "image_auroc", "value": 0.9},
                "tolerance": {"direction": "higher_is_better"},
            },
        }
    )


def _evidence_with_category(category: str) -> Evidence:
    return Evidence.model_validate(
        {
            "evidence_id": "ev-cat",
            "tier": "real",
            "outreach_origin": "external",
            "synthetic_source": None,
            "pcq_record": {
                "intent": {
                    "goal": "exploration",
                    "expected_baseline": {"metric": "image_auroc"},
                    "tolerance": {"direction": "higher_is_better"},
                },
                "data_fingerprint": {"modality": "vision", "sample_count_band": "100-1k"},
                "config": {"recipe_id": "mvtec-patchcore", "category": category},
                "metrics": {"image_auroc": 0.96},
                "worker_spec": {"cpu_cores": 8, "ram_gb": 16},
                "attribution": {"operator": None},
                "contract_version": "2.0",
            },
        }
    )


def test_serialize_query_with_category_description_includes_it():
    """intent.description의 카테고리 신호가 query 검색 텍스트에 들어간다."""
    text = serialize_query(_query_with_description("MVTec screw anomaly detection, beat 0.86"))
    assert "screw" in text.lower()


def test_serialize_query_without_description_is_unaffected():
    """description 없으면 기존 직렬화 유지 (회귀 방지)."""
    text = serialize_query(_query_with_description(""))
    assert "vision dataset" in text.lower()
    assert "goal" in text.lower()


def test_serialize_evidence_with_category_includes_it():
    """evidence config.category가 검색 텍스트에 들어간다."""
    text = serialize_evidence(_evidence_with_category("screw"))
    assert "screw" in text.lower()
