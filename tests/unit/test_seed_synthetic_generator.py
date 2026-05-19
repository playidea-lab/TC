"""synthetic generator — fake oracle로 LLM 호출 우회."""

import pytest

from the_commons.library.content_hash import verify_integrity
from the_commons.seed.synthetic_generator import (
    SeedSpec,
    SyntheticOracle,
    SyntheticPrediction,
    build_synthetic_record,
    generate_seed_records,
)


class _FakeOracle:
    """결정적 prediction을 반환 — test 재현 가능."""

    async def predict(self, spec: SeedSpec) -> SyntheticPrediction:
        return SyntheticPrediction(
            expected_metric_name="AUC",
            expected_metric_value=0.85,
            estimated_runtime_sec=180,
            hyperparams={"lr": 0.05, "n_estimators": 300},
            reasoning=f"LightGBM strong on {spec.modality} {spec.sample_count_band}",
        )


class _FailingOracle:
    """항상 예외 — graceful skip 검증."""

    async def predict(self, spec: SeedSpec) -> SyntheticPrediction:
        raise RuntimeError("LLM 호출 실패")


def test_fake_oracle_is_protocol_compatible() -> None:
    assert isinstance(_FakeOracle(), SyntheticOracle)


def test_build_synthetic_record_is_pcq_2x_compliant() -> None:
    """생성된 record는 schema·attribution·tier 모두 정합."""
    spec = SeedSpec(
        modality="tabular",
        sample_count_band="10k-100k",
        intent_goal="sota_challenge",
        recipe_id="lightgbm",
        framework="lightgbm",
    )
    prediction = SyntheticPrediction(
        expected_metric_name="AUC",
        expected_metric_value=0.85,
        estimated_runtime_sec=180,
        hyperparams={"lr": 0.05},
        reasoning="strong baseline",
    )
    rec = build_synthetic_record(
        spec,
        prediction,
        source_model="gemini-flash-2.5",
        prompt_hash="sha256:abc",
        evidence_id_suffix="t-001",
    )

    assert rec["tier"] == "synthetic"
    assert rec["outreach_origin"] == "internal"
    pcq = rec["pcq_record"]
    assert pcq["intent"]["goal"] == "sota_challenge"
    assert pcq["intent"]["expected_baseline"] == {"metric": "AUC", "value": 0.85}
    assert rec["synthetic_source"]["source_model"] == "gemini-flash-2.5"
    assert rec["synthetic_source"]["prompt_hash"] == "sha256:abc"
    assert pcq["contract_version"] == "2.0"


def test_build_synthetic_record_content_hash_self_verifies() -> None:
    """build_synthetic_record는 content_hash를 채워서 verify_content_hash 통과."""
    spec = SeedSpec(
        modality="tabular",
        sample_count_band="1k-10k",
        intent_goal="exploration",
        recipe_id="tabpfn",
    )
    prediction = SyntheticPrediction(
        expected_metric_name="AUC",
        expected_metric_value=0.82,
        estimated_runtime_sec=30,
        hyperparams={},
        reasoning="small data sweet spot",
    )
    rec = build_synthetic_record(
        spec, prediction, source_model="x", prompt_hash="sha256:y", evidence_id_suffix="z"
    )
    integ = rec["pcq_record"]["integrity"]
    assert verify_integrity(rec["pcq_record"], integ["content_hash"]) is True


async def test_generate_seed_records_returns_one_record_per_spec() -> None:
    """N개 spec → N개 record (oracle 성공 시)."""
    specs = [
        SeedSpec(
            modality="tabular",
            sample_count_band="1k-10k",
            intent_goal="exploration",
            recipe_id="lightgbm",
        ),
        SeedSpec(
            modality="tabular",
            sample_count_band="10k-100k",
            intent_goal="sota_challenge",
            recipe_id="xgboost",
        ),
    ]
    records = await generate_seed_records(
        _FakeOracle(), specs, source_model="gemini-flash-2.5"
    )
    assert len(records) == 2
    assert all(r["tier"] == "synthetic" for r in records)
    assert records[0]["pcq_record"]["config"]["recipe_id"] == "lightgbm"
    assert records[1]["pcq_record"]["config"]["recipe_id"] == "xgboost"


async def test_generate_seed_records_skips_failing_oracle_calls() -> None:
    """oracle 예외 시 해당 spec은 skip, 다른 spec은 진행."""
    specs = [
        SeedSpec(
            modality="tabular",
            sample_count_band="1k-10k",
            intent_goal="exploration",
            recipe_id="lightgbm",
        ),
    ]
    records = await generate_seed_records(_FailingOracle(), specs, source_model="x")
    assert records == []


async def test_generated_records_have_unique_evidence_ids() -> None:
    """index suffix로 evidence_id 중복 방지."""
    specs = [
        SeedSpec(
            modality="tabular",
            sample_count_band=band,
            intent_goal="exploration",
            recipe_id="lightgbm",
        )
        for band in ["1k-10k", "10k-100k", "100k-1M"]
    ]
    records = await generate_seed_records(
        _FakeOracle(), specs, source_model="gemini-flash-2.5"
    )
    ids = {r["evidence_id"] for r in records}
    assert len(ids) == 3


@pytest.mark.parametrize("recipe_id", ["lightgbm", "xgboost", "tabpfn"])
def test_recipe_appears_in_record_config(recipe_id: str) -> None:
    """spec.recipe_id가 그대로 record config에 들어간다."""
    spec = SeedSpec(
        modality="tabular",
        sample_count_band="10k-100k",
        intent_goal="exploration",
        recipe_id=recipe_id,
    )
    prediction = SyntheticPrediction(
        expected_metric_name="AUC",
        expected_metric_value=0.8,
        estimated_runtime_sec=60,
        hyperparams={},
        reasoning="x",
    )
    rec = build_synthetic_record(
        spec, prediction, source_model="x", prompt_hash="sha256:y", evidence_id_suffix="z"
    )
    assert rec["pcq_record"]["config"]["recipe_id"] == recipe_id
