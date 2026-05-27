"""describe_run(pcq) → TC evidence 어댑터.

pcq가 본질 계약(envelope)을 만들고 TC는 그것을 받아 저장한다(역할 분리). 이
어댑터는 pcq `describe_run` dict를 TC Evidence 양식으로 변환한다:

- intent/attribution/code/seeds/data_ref는 `extra='allow'` 덕에 패스스루.
- `fingerprint`→`data_fingerprint`, `worker_spec`은 TC 필수 필드(sample_count_band /
  cpu_cores / ram_gb)만 보강하고 describe 원본 필드는 함께 보존.
- config는 P5 `reproducibility_evidence.config.hyperparams` 본문을 flatten →
  `{recipe_id, **hyperparams}` (within_synth가 읽을 본질 hyperparam).
- metrics는 `best.metrics`(없으면 `{target_metric: best_value}`).
- integrity는 TC allowlist로 재계산 — pcq integrity는 워커-측, TC integrity는
  도서관-측 검증으로 양립(어댑터가 config를 재구조화하므로 pcq hash는 무효).
"""

from typing import Any

from the_commons.library.content_hash import compute_integrity


def _extract_metrics(desc: dict[str, Any]) -> dict[str, Any]:
    """best epoch의 metrics(flat) 추출. 없으면 {target_metric: best_value}."""
    best = desc.get("best") or {}
    metrics = dict(best.get("metrics") or {})
    if metrics:
        return metrics
    tm = desc.get("target_metric")
    bv = desc.get("best_value")
    if tm and isinstance(bv, int | float):
        return {tm: bv}
    return {}


def describe_to_evidence(
    desc: dict[str, Any],
    *,
    evidence_id: str,
    recipe_id: str,
    modality: str = "vision",
    sample_count_band: str = "100-1k",
    cpu_cores: int = 8,
    ram_gb: int = 16,
    intent_goal: str = "exploration",
    tier: str = "real",
    outreach_origin: str = "internal",
    lineage_target: str | None = None,
    branch: str = "manual",
) -> dict[str, Any]:
    """pcq describe_run dict → TC evidence envelope (ingest 입력)."""
    repro_cfg = (desc.get("reproducibility_evidence") or {}).get("config") or {}
    hyperparams = repro_cfg.get("hyperparams") or {}

    # data_fingerprint: describe 원본 패스스루 + TC 필수 필드 보강
    fingerprint = dict(desc.get("fingerprint") or {})
    fingerprint["modality"] = fingerprint.get("modality") or modality
    fingerprint.setdefault("sample_count_band", sample_count_band)

    # worker_spec: 패스스루 + TC 필수 필드 보강(cpu_cores/ram_gb ge=1)
    worker_spec = dict(desc.get("worker_spec") or {})
    worker_spec.setdefault("cpu_cores", cpu_cores)
    worker_spec.setdefault("ram_gb", ram_gb)

    pcq_record: dict[str, Any] = {
        "config": {"recipe_id": recipe_id, **hyperparams},
        "metrics": _extract_metrics(desc),
        "data_fingerprint": fingerprint,
        "worker_spec": worker_spec,
        "contract_version": desc.get("contract_version", "2.0"),
    }
    # intent: describe 패스스루 + goal 보강 (DB evidence.intent_goal NOT NULL)
    intent = dict(desc.get("intent") or {})
    intent.setdefault("goal", intent_goal)
    pcq_record["intent"] = intent
    # 나머지 패스스루 — 있을 때만 (absent-leaf)
    for key in ("attribution", "code", "seeds", "data_ref"):
        value = desc.get(key)
        if value is not None:
            pcq_record[key] = value

    # integrity는 TC allowlist 기준 재계산 (pcq integrity는 어댑터 변형으로 무효)
    pcq_record["integrity"] = compute_integrity(pcq_record)

    env: dict[str, Any] = {
        "evidence_id": evidence_id,
        "tier": tier,
        "outreach_origin": outreach_origin,
        "synthetic_source": None,
        "pcq_record": pcq_record,
    }
    if lineage_target:
        lineage_type = "exploration" if branch == "explore" else "derives_from"
        env["lineage"] = [{
            "type": lineage_type,
            "target_evidence_id": lineage_target,
            "metadata": {"branch": branch},
        }]
    return env
