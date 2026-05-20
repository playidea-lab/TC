"""evidence content hash 계산.

pcq 2.x 정본(`docs/vendor/pcq/`, pcq commit 5e86bee의
`build_integrity_object`)을 byte-for-byte 미러한다 — cross-impl 재현성이
거버넌스 게이트·corpus export의 토대다.

- 신규 정본 API: `compute_integrity` / `verify_integrity` (pcq_record 대상).
- 구 API `compute_content_hash` / `verify_content_hash` 는 Stage 2에서
  envelope·호출부 마이그레이션과 함께 제거 예정. 그때까지 잔존(호출부 불변).
"""

import hashlib
import json
from typing import Any

HASH_ALGO = "sha256"

# pcq 정본 미러 — src/pcq/contract.py:_INTEGRITY_HASHED_FIELDS (순서 유지).
# v4.10.0 Reproducibility Pack: code.content_sha256, code.scope, seeds,
# data_ref.content_sha256 추가.
_INTEGRITY_HASHED_FIELDS: list[str] = [
    "intent",
    "config",
    "metrics",
    "data_fingerprint",
    "worker_spec",
    "attribution.author",
    "attribution.committer",
    "attribution.operator",
    "contract_version",
    "code.content_sha256",
    "code.scope",
    "seeds",
    "data_ref.content_sha256",
]

# anti-recursion 제외 경로 — integrity 자신·Phase2 예약 signature.
_EXCLUDED: frozenset[str] = frozenset({"attribution.signature", "integrity"})

# v4.10.0 추가 leaf — None resolve 시 canonical subset에서 drop (PHI dual-gate
# 의미론: data_ref.content_sha256 stripped과 필드 absent 동일 hash).
# 기존 9 leaf는 include-None 유지 (pcq 5e86bee golden parity 보존).
_DROP_ABSENT_LEAVES: frozenset[str] = frozenset(
    {"code.content_sha256", "code.scope", "seeds", "data_ref.content_sha256"}
)


def _resolve_dotted_path(payload: dict[str, Any], path: str) -> object:
    """점 구분 경로로 payload에서 값 추출. 중간 non-dict/없으면 None.

    pcq src/pcq/contract.py:_resolve_dotted_path 정확 미러.
    """
    current: object = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def compute_integrity(
    pcq_record: dict[str, Any],
    hashed_fields: list[str] | None = None,
) -> dict[str, Any]:
    """pcq_record → {"content_hash", "hashed_fields"} (pcq 정본 byte-parity).

    canonical form: json.dumps(subset, indent=2, sort_keys=True, default=str).
    indent=2가 빠지면 pcq hash를 재현하지 못한다 (정본 규약).

    `hashed_fields`는 pcq build_integrity_object와 동일 시그니처 — None이면
    기본 allowlist. 독립 verifier가 record의 *선언된* allowlist로 재현할 수
    있도록 받는다(다른 allowlist로 만든 record도 검증 가능). _EXCLUDED는
    인자 여부와 무관하게 항상 필터(anti-recursion).
    """
    base = _INTEGRITY_HASHED_FIELDS if hashed_fields is None else hashed_fields
    fields_to_use = [f for f in base if f not in _EXCLUDED]
    subset: dict[str, object] = {}
    for path in fields_to_use:
        value = _resolve_dotted_path(pcq_record, path)
        # v4.10.0 신규 leaf는 None 시 drop (PHI dual-gate ≡ absent).
        # 기존 9 leaf는 include-None 유지 (5e86bee golden parity).
        if value is None and path in _DROP_ABSENT_LEAVES:
            continue
        subset[path] = value
    canonical = json.dumps(subset, indent=2, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "content_hash": f"{HASH_ALGO}:{digest}",
        "hashed_fields": fields_to_use,
    }


def verify_integrity(
    pcq_record: dict[str, Any], expected_content_hash: str
) -> bool:
    """pcq_record 재계산 content_hash가 expected와 일치하는지 검증.

    record가 `integrity.hashed_fields`를 선언했으면 *그 allowlist*로 재현
    한다 (다른 allowlist로 produce된 record도 충실히 검증 — 정본 verifier
    의미). 선언이 없으면 기본 allowlist.
    """
    declared = _resolve_dotted_path(pcq_record, "integrity.hashed_fields")
    fields = declared if isinstance(declared, list) and declared else None
    return (
        compute_integrity(pcq_record, fields)["content_hash"]
        == expected_content_hash
    )


def compute_content_hash(record: dict[str, Any]) -> str:
    """canonical JSON 직렬화 → SHA256 hex digest.

    Args:
        record: pcq 2.x evidence record. `attribution.content_hash` 키가
            있으면 자동으로 제외하고 계산한다.

    Returns:
        예: `sha256:abc123...`
    """
    payload = _strip_content_hash(record)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{HASH_ALGO}:{digest}"


def verify_content_hash(record: dict[str, Any]) -> bool:
    """attribution.content_hash 필드가 실제 hash와 일치하는지 검증.

    L1 immutability 위반 (DB record 변조) 감지에 사용.
    """
    attribution = record.get("attribution") or {}
    expected = attribution.get("content_hash")
    if not expected:
        return False
    actual = compute_content_hash(record)
    return actual == expected


def _strip_content_hash(record: dict[str, Any]) -> dict[str, Any]:
    """hash 계산 입력에서 *server-set* 필드를 제외한 shallow-clone.

    제외 대상:
    - attribution.content_hash (chicken-and-egg, 기존)
    - synthetic_source.verifier (server-derived, L1 immutable 정합)
    """
    cloned = dict(record)

    if "attribution" in cloned:
        attribution = dict(cloned["attribution"])
        attribution.pop("content_hash", None)
        cloned["attribution"] = attribution

    if isinstance(cloned.get("synthetic_source"), dict):
        synthetic = dict(cloned["synthetic_source"])
        synthetic.pop("verifier", None)
        cloned["synthetic_source"] = synthetic

    return cloned
