"""attribution 검증.

ingestion 시점에 record가:
- synthetic tier면 synthetic_source 필수
- attribution.content_hash가 실제 record hash와 일치
- pcq_version이 지원 범위(2.x)
- evidence_id가 일정 패턴
"""

from typing import Any

from the_commons.library.content_hash import compute_content_hash

SUPPORTED_PCQ_MAJOR = 2
EVIDENCE_ID_PREFIX = "ev-"


class AttributionError(ValueError):
    """attribution 검증 실패. ingestion이 거부할 record."""


def validate_attribution(record: dict[str, Any]) -> None:
    """검증 통과면 None, 실패면 AttributionError.

    DB 저장 전 ingestion 파이프라인이 마지막 게이트로 호출한다.
    """
    _require_evidence_id(record)
    _require_tier_attribution_consistency(record)
    _require_pcq_version(record)
    _require_content_hash_match(record)


def _require_evidence_id(record: dict[str, Any]) -> None:
    eid = record.get("evidence_id")
    if not isinstance(eid, str) or not eid.startswith(EVIDENCE_ID_PREFIX):
        raise AttributionError(
            f"evidence_id 필요, '{EVIDENCE_ID_PREFIX}' 접두어 필수 (받은 값: {eid!r})"
        )


def _require_tier_attribution_consistency(record: dict[str, Any]) -> None:
    """synthetic tier는 synthetic_source 필수, real tier는 None이어야."""
    tier = record.get("tier")
    src = record.get("synthetic_source")

    if tier == "synthetic":
        if not isinstance(src, dict):
            raise AttributionError(
                "tier='synthetic' 인데 synthetic_source 누락"
            )
        for field in ("source_model", "prompt_hash", "generated_at"):
            if not src.get(field):
                raise AttributionError(f"synthetic_source.{field} 누락")
    elif tier == "real":
        if src not in (None, {}):
            raise AttributionError(
                "tier='real' 인데 synthetic_source가 채워져 있음 — 일관성 위반"
            )
    else:
        raise AttributionError(f"unknown tier: {tier!r}")


def _require_pcq_version(record: dict[str, Any]) -> None:
    attribution = record.get("attribution", {})
    version = attribution.get("pcq_version", "")
    if not isinstance(version, str) or not version:
        raise AttributionError("attribution.pcq_version 누락")
    major_str = version.split(".", 1)[0]
    if not major_str.isdigit() or int(major_str) != SUPPORTED_PCQ_MAJOR:
        raise AttributionError(
            f"지원하지 않는 pcq 버전: {version} (필요: {SUPPORTED_PCQ_MAJOR}.x)"
        )


def _require_content_hash_match(record: dict[str, Any]) -> None:
    """attribution.content_hash가 record로부터 재계산한 hash와 일치해야."""
    attribution = record.get("attribution", {})
    declared = attribution.get("content_hash")
    if not declared:
        raise AttributionError("attribution.content_hash 누락")
    actual = compute_content_hash(record)
    if declared != actual:
        raise AttributionError(
            f"content_hash 불일치 — declared={declared}, computed={actual}"
        )
