"""Serializer template v1 단위 테스트."""

from datetime import UTC, datetime

from the_commons.library.models import (
    DataFingerprint,
    Evidence,
    Intent,
    SyntheticSource,
    WorkerSpec,
)
from the_commons.matchmaker.serializer import (
    QueryFeatures,
    default_registry,
)


def _query(**overrides) -> QueryFeatures:
    base = {
        "worker_spec": WorkerSpec(
            cpu_cores=32, ram_gb=64, gpu_model="RTX 5080", vram_gb=16, has_gpu=True
        ),
        "data_fingerprint": DataFingerprint(
            modality="tabular",
            sample_count_band="10k-100k",
        ),
        "intent": Intent(goal="exploration"),
    }
    base.update(overrides)
    return QueryFeatures(**base)


def _evidence(**overrides) -> Evidence:
    pcq_overrides = overrides.pop("pcq", {})
    pcq = {
        "intent": {"goal": "exploration"},
        "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
        "config": {"recipe_id": "lightgbm", "lr": 0.05},
        "metrics": {"AUC": 0.8475},
        "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
        "attribution": {"operator": None},
        "contract_version": "2.0",
    }
    pcq.update(pcq_overrides)
    base = {
        "evidence_id": "ev-t",
        "tier": "real",
        "outreach_origin": "external",
        "synthetic_source": None,
        "pcq_record": pcq,
    }
    base.update(overrides)
    return Evidence.model_validate(base)


def test_registry_default_supports_v1() -> None:
    """default registry에 v1이 등록되어 있어야."""
    assert "v1" in default_registry().known_versions


def test_serialize_query_includes_modality_band_hardware_goal() -> None:
    """query 직렬화에 핵심 요소 모두 포함."""
    text = default_registry().serialize_query(_query(), version="v1")

    assert "tabular dataset" in text
    assert "10k-100k samples" in text
    assert "GPU RTX 5080" in text
    assert "64GB RAM" in text
    assert "explore" in text  # goal phrase


def test_serialize_query_with_baseline_includes_target() -> None:
    """expected_baseline이 있으면 target 문구 포함."""
    query = _query(
        intent=Intent(
            goal="sota_challenge",
            expected_baseline={"metric": "AUC", "value": 0.85},
            tolerance={"direction": "higher_is_better", "margin": 0.02},
        )
    )
    text = default_registry().serialize_query(query, version="v1")
    assert "target AUC=0.85" in text
    assert "challenge state-of-the-art" in text


def test_serialize_query_with_cpu_only_omits_gpu() -> None:
    """GPU 없으면 CPU 표현."""
    query = _query(
        worker_spec=WorkerSpec(cpu_cores=16, ram_gb=32, has_gpu=False),
    )
    text = default_registry().serialize_query(query, version="v1")
    assert "CPU 16 cores" in text
    assert "GPU" not in text


def test_serialize_evidence_includes_recipe_metric_tier() -> None:
    """evidence 직렬화에 recipe, metric, tier 명시."""
    text = default_registry().serialize_evidence(_evidence(), version="v1")
    assert "lightgbm" in text
    assert "AUC=0.8475" in text
    assert "real" in text


def test_serialize_evidence_with_synthetic_tier_labels_distillation() -> None:
    """synthetic tier는 'LLM-distilled' 표시."""
    syn_source = SyntheticSource(
        source_model="gemini-flash-2.5",
        prompt_hash="sha256:x",
        generated_at=datetime.now(UTC),
    )
    ev = _evidence(tier="synthetic", synthetic_source=syn_source)

    text = default_registry().serialize_evidence(ev, version="v1")
    assert "synthetic" in text.lower()
    assert "LLM-distilled" in text


def test_serialize_unknown_version_raises() -> None:
    """등록되지 않은 version은 ValueError."""
    import pytest

    with pytest.raises(ValueError, match="unknown serializer version"):
        default_registry().serialize_query(_query(), version="v99")


def test_serialize_query_includes_statistical_moments_when_present() -> None:
    """statistical_moments가 있으면 description에 포함."""
    query = _query(
        data_fingerprint=DataFingerprint(
            modality="tabular",
            sample_count_band="10k-100k",
            statistical_moments={"class_balance": "5-15%", "missing_pct": "0-5%"},
        )
    )
    text = default_registry().serialize_query(query, version="v1")
    assert "class balance 5-15%" in text
    assert "missing 0-5%" in text
