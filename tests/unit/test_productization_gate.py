"""서비스화 게이트 — C1/C2/C3 산정 + 측정불가(거짓통과 금지) + escape 단위 테스트."""

from datetime import UTC, datetime

import pytest

from the_commons.library.models import Evidence
from the_commons.library.store import InMemoryEvidenceStore
from the_commons.reciprocity.productization_gate import build_productization_gate
from the_commons.reciprocity.verdict_report import VerdictReport
from the_commons.settings import settings


def _verdict(
    *,
    branch: str = "success",
    strengthened: bool = True,
    promote: int = 0,
    contradicts: int = 0,
) -> VerdictReport:
    return VerdictReport(
        counts={
            "loop_closure": 1,
            "promote": promote,
            "contradicts": contradicts,
            "promote_or_contradict": promote + contradicts,
        },
        counts_by_origin={"internal": 1, "external": 1 if strengthened else 0},
        branch=branch,  # type: ignore[arg-type]
        strengthened=strengthened,
        detail="",
    )


def _ev(eid: str, tier: str) -> Evidence:
    rec = {
        "evidence_id": eid,
        "tier": tier,
        "outreach_origin": "external",
        "synthetic_source": None,
        "pcq_record": {
            "intent": {"goal": "exploration", "expected_baseline": None, "tolerance": None},
            "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
            "config": {"recipe_id": "rf"},
            "metrics": {"AUC": 0.8},
            "worker_spec": {"cpu_cores": 8, "ram_gb": 16},
            "attribution": {"operator": None},
            "contract_version": "2.0",
        },
    }
    return Evidence.model_validate(rec)


async def _store(real: int, synthetic: int) -> InMemoryEvidenceStore:
    s = InMemoryEvidenceStore()
    for i in range(real):
        await s.insert(_ev(f"r{i}", "real"))
    for i in range(synthetic):
        await s.insert(_ev(f"s{i}", "synthetic"))
    return s


@pytest.fixture(autouse=True)
def _set_thresholds(monkeypatch):
    # 테스트는 명시적으로 임계를 설정 (sentinel 거동도 별도 테스트)
    monkeypatch.setattr(settings, "productization_promote_rate_floor", 0.7)
    monkeypatch.setattr(settings, "productization_min_reproductions", 4)
    monkeypatch.setattr(settings, "productization_gate_escape_windows", 0)


async def test_c3_below_min_reproductions_is_none_not_pass() -> None:
    # (promote+contradicts)=3 < min 4 → C3 측정 불가(None), 트립 금지
    g = await build_productization_gate(
        _verdict(promote=3, contradicts=0), await _store(10, 1)
    )
    assert g.c3_quality is None
    assert g.tripped is False
    assert "C3" in g.diagnostic


async def test_c3_floor_unset_sentinel_is_none(monkeypatch) -> None:
    monkeypatch.setattr(settings, "productization_promote_rate_floor", -1.0)
    g = await build_productization_gate(
        _verdict(promote=9, contradicts=1), await _store(10, 1)
    )
    assert g.c3_quality is None  # 미설정 → 측정 불가 (거짓 통과 금지)
    assert g.tripped is False


async def test_c3_meets_floor_true() -> None:
    # promote-rate = 8/(8+2)=0.8 ≥ 0.7, N=10 ≥ 4 → C3 True
    g = await build_productization_gate(
        _verdict(promote=8, contradicts=2), await _store(10, 1)
    )
    assert g.c3_quality is True


async def test_c3_below_floor_false() -> None:
    g = await build_productization_gate(
        _verdict(promote=2, contradicts=6), await _store(10, 1)
    )
    assert g.c3_quality is False
    assert g.tripped is False


async def test_c1_requires_success_and_strengthened() -> None:
    g_int = await build_productization_gate(
        _verdict(strengthened=False, promote=8, contradicts=2), await _store(10, 1)
    )
    assert g_int.c1_strengthened_success is False
    assert g_int.tripped is False

    g_fail = await build_productization_gate(
        _verdict(branch="partial", promote=8, contradicts=2), await _store(10, 1)
    )
    assert g_fail.c1_strengthened_success is False


async def test_c2_synthetic_dominant_blocks_trip() -> None:
    g = await build_productization_gate(
        _verdict(promote=8, contradicts=2), await _store(1, 20)
    )
    assert g.c2_corpus_density is False
    assert g.tripped is False


async def test_all_three_satisfied_trips() -> None:
    g = await build_productization_gate(
        _verdict(promote=8, contradicts=2), await _store(20, 1)
    )
    assert g.c1_strengthened_success is True
    assert g.c2_corpus_density is True
    assert g.c3_quality is True
    assert g.tripped is True


async def test_forced_decision_only_at_escape_boundary(monkeypatch) -> None:
    monkeypatch.setattr(settings, "productization_gate_escape_windows", 2)
    v = _verdict(branch="partial", promote=0, contradicts=0)
    s = await _store(20, 1)

    g1 = await build_productization_gate(v, s, consecutive_untripped_windows=1)
    assert g1.forced_decision is None

    g2 = await build_productization_gate(v, s, consecutive_untripped_windows=2)
    assert g2.forced_decision is not None
    assert "재결정" in g2.forced_decision


async def test_forced_decision_disabled_when_escape_windows_zero() -> None:
    # autouse fixture: escape_windows=0 → 항상 None
    g = await build_productization_gate(
        _verdict(branch="failure"), await _store(20, 1),
        consecutive_untripped_windows=99,
    )
    assert g.forced_decision is None
