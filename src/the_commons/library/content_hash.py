"""evidence content hash 계산.

L1 immutability를 *검증 가능*하게 만드는 기반. 같은 evidence는 같은 hash,
필드 한 글자만 바뀌어도 다른 hash. attribution.content_hash 필드 자체는
계산 입력에서 제외 (chicken-and-egg).
"""

import hashlib
import json
from typing import Any

HASH_ALGO = "sha256"


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
