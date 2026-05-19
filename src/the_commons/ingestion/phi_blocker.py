"""PHI 자동 차단 — TC의 "공개/private binary" 약속을 시스템 차원에서 보장.

contributor가 매번 "어디까지 공개?"를 고민할 필요 없게 한다. ingestion 단계에서:
- raw 데이터 (sample/image/text) 발견 → 거부
- 직접 식별자 (이름/이메일/환자ID) 발견 → 거부
- 정확한 sample count → 대역으로 자동 quantize (silent)
"""

from typing import Any

# 발견 즉시 거부할 키 (raw payload 또는 직접 식별자)
DISALLOWED_KEYS_EXACT: frozenset[str] = frozenset(
    {
        # raw 데이터
        "raw_samples",
        "raw_image",
        "raw_images",
        "raw_text",
        "raw_texts",
        "rows",
        "samples",
        # 직접 식별자
        "patient_id",
        "patient_name",
        "patient_ids",
        "email",
        "emails",
        "phone",
        "phones",
        "ssn",
        "user_name",
        "real_name",
    }
)

# sample_count 정확값 → 대역으로 quantize 매핑
# (lower_inclusive, upper_exclusive, label)
_SAMPLE_COUNT_BANDS: list[tuple[int, int, str]] = [
    (0, 100, "0-100"),
    (100, 1_000, "100-1k"),
    (1_000, 10_000, "1k-10k"),
    (10_000, 100_000, "10k-100k"),
    (100_000, 1_000_000, "100k-1M"),
    (1_000_000, 10_000_000, "1M-10M"),
]
_SAMPLE_COUNT_TOP_BAND = "10M+"


class PHIViolationError(ValueError):
    """PHI 차단 규정 위반. ingestion이 거부해야 하는 record."""


def quantize_sample_count(count: int) -> str:
    """정확한 N → 대역 라벨. 음수는 0으로 clamp."""
    if count < 0:
        return _SAMPLE_COUNT_BANDS[0][2]
    for lower, upper, label in _SAMPLE_COUNT_BANDS:
        if lower <= count < upper:
            return label
    return _SAMPLE_COUNT_TOP_BAND


def block_phi(record: dict[str, Any]) -> dict[str, Any]:
    """PHI 차단 + sample count 자동 quantize.

    Args:
        record: pcq 2.x evidence record (dict 형태)

    Returns:
        정화된 record (얕은 사본). 정확 sample count는 대역으로 변환됨.

    Raises:
        PHIViolationError: raw 데이터·직접 식별자 발견 시
    """
    violations: list[str] = []
    _scan_disallowed(record, path="$", violations=violations)
    if violations:
        raise PHIViolationError(
            "PHI 차단 위반 발견: " + ", ".join(violations[:10])
        )

    cleaned = _quantize_sample_count_inplace(record)
    return cleaned


def _scan_disallowed(node: Any, *, path: str, violations: list[str]) -> None:
    """nested dict/list 전체 스캔 — DISALLOWED_KEYS_EXACT 발견 시 violation 등록."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in DISALLOWED_KEYS_EXACT:
                violations.append(f"{path}.{key}")
            _scan_disallowed(value, path=f"{path}.{key}", violations=violations)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            _scan_disallowed(item, path=f"{path}[{idx}]", violations=violations)


def _quantize_sample_count_inplace(record: dict[str, Any]) -> dict[str, Any]:
    """envelope 형태에서 pcq_record.data_fingerprint 정확 sample_count 대역 변환."""
    cloned = _deep_copy_shallow(record)

    # envelope: pcq_record 안의 data_fingerprint를 스코프 (R9).
    pcq = cloned.get("pcq_record")
    if not isinstance(pcq, dict):
        return cloned
    pcq = dict(pcq)  # shallow clone
    fingerprint = pcq.get("data_fingerprint")
    if not isinstance(fingerprint, dict):
        cloned["pcq_record"] = pcq
        return cloned
    fingerprint = dict(fingerprint)

    exact = fingerprint.get("sample_count")
    if isinstance(exact, int):
        fingerprint["sample_count_band"] = quantize_sample_count(exact)
        fingerprint.pop("sample_count", None)

    pcq["data_fingerprint"] = fingerprint
    cloned["pcq_record"] = pcq
    return cloned


def _deep_copy_shallow(record: dict[str, Any]) -> dict[str, Any]:
    """1단계 deep clone — 최상위 dict 키별로 dict 복사. 이상 부족 시 json.loads 권장."""
    return {k: dict(v) if isinstance(v, dict) else v for k, v in record.items()}
