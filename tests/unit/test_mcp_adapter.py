"""describe_run → TC evidence 어댑터 단위 테스트.

실제 pcq describe_run 출력 형태(reproducibility_evidence.config.hyperparams,
best.metrics, fingerprint/worker_spec 중첩 dict)를 샘플로 변환 → TC Evidence
model_validate 통과 + config flatten/metrics/integrity/lineage 검증.
"""

from __future__ import annotations

from the_commons.library.models import Evidence
from the_commons.mcp.adapter import describe_to_evidence


def _sample_describe() -> dict:
    """pcq describe_run().to_dict() 형태 (P5 hyperparams 본문 포함)."""
    return {
        "schema_version": 1,
        "run_id": "run-abc",
        "status": "completed",
        "target_metric": "image_auroc",
        "best": {"epoch": 5, "metrics": {"image_auroc": 0.84, "pixel_auroc": 0.71}},
        "best_value": 0.84,
        "contract_version": "2.0",
        # 중첩 dict (T-PCQ2X/T-PCQRP 패스스루)
        "intent": {"goal": "exploration",
                   "expected_baseline": {"metric": "image_auroc", "value": 0.9},
                   "tolerance": {"direction": "higher_is_better", "margin": 0.02}},
        "fingerprint": {"modality": "vision", "task_kind": "anomaly", "n_samples": 200},
        "worker_spec": {"cpu_model": "M3", "memory_gb": 16.0, "accelerator_kind": "mps"},
        "attribution": {"author": {"id": "claude-code", "kind": "agent"}, "operator": "cc"},
        "code": {"content_sha256": "abc123", "content": "print('@image_auroc=0.84')",
                 "scope": {"kind": "entry_script", "files": ["train.py"]},
                 "requirements": ["torch"]},
        "seeds": {"main": 42},
        "data_ref": {"uri": "file:///data/bottle", "content_sha256": "d00d"},
        "reproducibility_evidence": {
            "config": {"config_json_sha256": "cfg00", "seed": 42,
                       "hyperparams": {"lr": 0.001, "backbone": "wresnet50"}},
        },
    }


def test_adapter_output_passes_evidence_validation() -> None:
    env = describe_to_evidence(_sample_describe(), evidence_id="ev-x", recipe_id="patchcore")
    # TC Evidence 양식으로 검증 통과해야 (ingest가 받을 수 있음)
    ev = Evidence.model_validate(env)
    assert ev.evidence_id == "ev-x"
    assert ev.tier == "real"


def test_adapter_flattens_hyperparams_into_config() -> None:
    env = describe_to_evidence(_sample_describe(), evidence_id="ev-x", recipe_id="patchcore")
    cfg = env["pcq_record"]["config"]
    assert cfg["recipe_id"] == "patchcore"
    assert cfg["lr"] == 0.001  # P5 hyperparam 본문이 within_synth가 읽을 config로
    assert cfg["backbone"] == "wresnet50"


def test_adapter_extracts_best_metrics() -> None:
    env = describe_to_evidence(_sample_describe(), evidence_id="ev-x", recipe_id="patchcore")
    assert env["pcq_record"]["metrics"] == {"image_auroc": 0.84, "pixel_auroc": 0.71}


def test_adapter_metrics_falls_back_to_target_best_value() -> None:
    desc = _sample_describe()
    desc["best"] = {}  # best.metrics 없음 → {target_metric: best_value}
    env = describe_to_evidence(desc, evidence_id="ev-x", recipe_id="patchcore")
    assert env["pcq_record"]["metrics"] == {"image_auroc": 0.84}


def test_adapter_fills_required_fields_keeps_describe_originals() -> None:
    env = describe_to_evidence(_sample_describe(), evidence_id="ev-x", recipe_id="patchcore",
                               sample_count_band="100-1k")
    fp = env["pcq_record"]["data_fingerprint"]
    assert fp["modality"] == "vision"
    assert fp["sample_count_band"] == "100-1k"  # TC 필수 보강
    assert fp["task_kind"] == "anomaly"  # describe 원본 보존(extra=allow)
    ws = env["pcq_record"]["worker_spec"]
    assert ws["cpu_cores"] == 8 and ws["ram_gb"] == 16  # TC 필수 보강
    assert ws["cpu_model"] == "M3"  # describe 원본 보존


def test_adapter_recomputes_integrity() -> None:
    env = describe_to_evidence(_sample_describe(), evidence_id="ev-x", recipe_id="patchcore")
    integ = env["pcq_record"]["integrity"]
    assert integ["content_hash"]  # TC allowlist 기준 재계산됨


def test_adapter_explore_lineage_is_exploration() -> None:
    env = describe_to_evidence(_sample_describe(), evidence_id="ev-2", recipe_id="ddad",
                               lineage_target="ev-1", branch="explore")
    assert env["lineage"][0]["type"] == "exploration"
    assert env["lineage"][0]["target_evidence_id"] == "ev-1"


def test_adapter_exploit_lineage_is_derives_from() -> None:
    env = describe_to_evidence(_sample_describe(), evidence_id="ev-3", recipe_id="patchcore",
                               lineage_target="ev-1", branch="exploit")
    assert env["lineage"][0]["type"] == "derives_from"
