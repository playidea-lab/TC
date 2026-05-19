"""attribution / integrity 검증 — envelope 정본 (R9/R12 정합).

ingestion 시점에 envelope record가:
- evidence_id 패턴
- synthetic tier ↔ synthetic_source 일관성
- pcq_record.contract_version이 지원 범위 (또는 부재 → "1.x", R6 additive)
- pcq_record.integrity.content_hash가 재계산과 일치 (integrity 부재면
  ingestion 상류가 server-derive 후 검증 — 부재는 더 이상 valid가 아님)
"""

import re
from typing import Any

from the_commons.library.content_hash import compute_integrity, verify_integrity

SUPPORTED_CONTRACT_VERSIONS: frozenset[str] = frozenset({"2.0", "1.x"})
EVIDENCE_ID_PREFIX = "ev-"
EVIDENCE_ID_PATTERN = re.compile(r"^ev-[A-Za-z0-9_-]+$")
EVIDENCE_ID_MIN_LENGTH = 4
EVIDENCE_ID_MAX_LENGTH = 128


class AttributionError(ValueError):
    """attribution/integrity 검증 실패 — ingestion이 거부할 record."""


def validate_attribution(record: dict[str, Any]) -> None:
    """envelope record 검증. 통과면 None, 실패면 AttributionError.

    pcq_record가 envelope의 첫째 시민(R9). 모든 pcq 2.x 필드는 그 안에서.
    """
    _require_evidence_id(record)
    _require_tier_synthetic_consistency(record)
    _require_contract_version(record)
    _require_integrity_hash_match(record)


def _require_evidence_id(record: dict[str, Any]) -> None:
    eid = record.get("evidence_id")
    if not isinstance(eid, str):
        raise AttributionError(
            f"evidence_id 필요 (받은 타입: {type(eid).__name__})"
        )
    if not (EVIDENCE_ID_MIN_LENGTH <= len(eid) <= EVIDENCE_ID_MAX_LENGTH):
        raise AttributionError(
            f"evidence_id 길이 {EVIDENCE_ID_MIN_LENGTH}-{EVIDENCE_ID_MAX_LENGTH} "
            f"범위여야 (받은 값 길이: {len(eid)})"
        )
    if not EVIDENCE_ID_PATTERN.match(eid):
        raise AttributionError(
            f"evidence_id 형식 위반 — 'ev-' 접두어 + 영숫자/하이픈/언더스코어만 "
            f"(받은 값: {eid!r})"
        )


def _require_tier_synthetic_consistency(record: dict[str, Any]) -> None:
    """synthetic tier는 synthetic_source 필수, real tier는 None이어야 (R10)."""
    tier = record.get("tier")
    src = record.get("synthetic_source")

    if tier == "synthetic":
        if not isinstance(src, dict):
            raise AttributionError("tier='synthetic' 인데 synthetic_source 누락")
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


def _require_contract_version(record: dict[str, Any]) -> None:
    """contract_version 부재 = 1.x (R6 additive). 그 외 모르는 버전이면 거부."""
    pcq = record.get("pcq_record") or {}
    version = pcq.get("contract_version")
    if version is None:
        return  # R6: 부재 = 1.x, valid
    if not isinstance(version, str) or version not in SUPPORTED_CONTRACT_VERSIONS:
        raise AttributionError(
            f"지원하지 않는 contract_version: {version!r} "
            f"(허용: {sorted(SUPPORTED_CONTRACT_VERSIONS)})"
        )


def _require_integrity_hash_match(record: dict[str, Any]) -> None:
    """pcq_record.integrity.content_hash가 재계산과 byte-parity 일치해야.

    1.x record는 integrity 부재 — ingestion 상류(`ensure_integrity`)가
    server-derive로 부착한 뒤 이 검증이 돈다. 그러므로 이 시점엔 integrity가
    있어야 한다 (없으면 상류 누락 — 거부).
    """
    pcq = record.get("pcq_record") or {}
    integrity = pcq.get("integrity") or {}
    declared = integrity.get("content_hash")
    if not declared:
        raise AttributionError("pcq_record.integrity.content_hash 누락")
    if not verify_integrity(pcq, declared):
        actual = compute_integrity(pcq)["content_hash"]
        raise AttributionError(
            f"content_hash 불일치 — declared={declared}, computed={actual}"
        )
