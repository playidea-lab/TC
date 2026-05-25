"""KR3/KR10: config 축별 metric 추세 순수계산 — 일기(사실)→교훈노트(패턴).

같은 recipe evidence들에서 numeric config 축의 (값, metric) 단조성을 계산한다.
LLM·DB·부작용 없는 순수 함수 → "시스템이 올바른 지식을 뽑는가"를 단위 테스트로 검증.
출력은 사실(추세)만 담고 처방(next_config)은 담지 않는다(KR6).
"""

import dataclasses

from the_commons.knowledge.trends import summarize_trends


def _s(recipe: str, config: dict, auroc: float):
    return (recipe, config, {"image_auroc": auroc})


def test_summarize_trends_numeric_axis_monotonic_increasing():
    samples = [
        _s("patchcore", {"memory_size": 10000, "img_size": 384}, 0.74),
        _s("patchcore", {"memory_size": 50000, "img_size": 384}, 0.91),
        _s("patchcore", {"memory_size": 100000, "img_size": 384}, 0.96),
    ]
    result = summarize_trends(samples, "image_auroc")
    assert len(result) == 1
    axes = {a.axis: a for a in result[0].axes}
    assert axes["memory_size"].direction == "increasing"
    # img_size는 유니크값 1개(384) → 추세 축에서 제외
    assert "img_size" not in axes


def test_summarize_trends_decreasing():
    samples = [
        _s("ae", {"latent_dim": 64}, 0.42),
        _s("ae", {"latent_dim": 128}, 0.30),
        _s("ae", {"latent_dim": 256}, 0.20),
    ]
    axes = {a.axis: a for a in summarize_trends(samples, "image_auroc")[0].axes}
    assert axes["latent_dim"].direction == "decreasing"


def test_summarize_trends_non_monotonic():
    samples = [
        _s("x", {"lr": 0.0001}, 0.5),
        _s("x", {"lr": 0.001}, 0.9),
        _s("x", {"lr": 0.01}, 0.4),
    ]
    axes = {a.axis: a for a in summarize_trends(samples, "image_auroc")[0].axes}
    assert axes["lr"].direction == "non_monotonic"


def test_summarize_trends_groups_by_recipe():
    samples = [
        _s("a", {"k": 1}, 0.5), _s("a", {"k": 2}, 0.6),
        _s("b", {"k": 1}, 0.7), _s("b", {"k": 2}, 0.8),
    ]
    result = summarize_trends(samples, "image_auroc")
    assert {rt.recipe_id for rt in result} == {"a", "b"}


def test_summarize_trends_ignores_non_numeric_axis():
    samples = [
        _s("p", {"backbone": "resnet18", "memory_size": 10000}, 0.8),
        _s("p", {"backbone": "wide_resnet50_2", "memory_size": 50000}, 0.9),
    ]
    axes = {a.axis: a for a in summarize_trends(samples, "image_auroc")[0].axes}
    assert "memory_size" in axes      # numeric 축
    assert "backbone" not in axes     # categorical(string) — KR3 범위 밖


def test_summarize_trends_output_has_no_prescription_field():
    # KR6: 출력에 처방(next_config 등) 필드가 없어야 한다 — 사실만, 판단은 에이전트
    samples = [_s("p", {"k": 1}, 0.5), _s("p", {"k": 2}, 0.6)]
    rt = summarize_trends(samples, "image_auroc")[0]
    names = {f.name for f in dataclasses.fields(rt)}
    assert "next_config" not in names
    assert "recommendation" not in names


def test_summarize_trends_real_5h_screw_patchcore():
    # 5h 실측 데이터(MVTec screw, PatchCore): memory 키울수록 auroc 증가
    samples = [
        _s("mvtec-patchcore", {"memory_size": 10000, "img_size": 384}, 0.7465),
        _s("mvtec-patchcore", {"memory_size": 50000, "img_size": 384}, 0.9106),
        _s("mvtec-patchcore", {"memory_size": 100000, "img_size": 384}, 0.9643),
    ]
    axes = {a.axis: a for a in summarize_trends(samples, "image_auroc")[0].axes}
    assert axes["memory_size"].direction == "increasing"
    assert axes["memory_size"].points[0] == (10000.0, 0.7465)


def test_summarize_trends_separates_by_target_category():
    # bottle(쉬움 1.0) vs screw(어려움) 섞임 — category 분리 안 하면 img가 허위로 보임.
    # category(target)별 그룹으로 분리해야 각 category 안에서 참 추세가 나온다.
    samples = [
        _s("ef", {"img_size": 256, "category": "bottle"}, 1.0),
        _s("ef", {"img_size": 384, "category": "bottle"}, 1.0),
        _s("ef", {"img_size": 256, "category": "screw"}, 0.80),
        _s("ef", {"img_size": 384, "category": "screw"}, 0.86),
    ]
    result = summarize_trends(samples, "image_auroc")  # group_axes 기본 ("category",)
    by_cat = {rt.group.get("category"): rt for rt in result}
    assert set(by_cat) == {"bottle", "screw"}
    screw_axes = {a.axis: a for a in by_cat["screw"].axes}
    assert screw_axes["img_size"].direction == "increasing"  # 256→0.80, 384→0.86
    assert "category" not in screw_axes  # target 축은 추세 축이 아니라 그룹 기준


def test_summarize_trends_aggregates_duplicate_axis_value_to_best():
    # 같은 memory_size에 두 점(img 다름) → max로 집계해 confounding 완화
    samples = [
        _s("pc", {"memory_size": 50000, "img_size": 384}, 0.91),
        _s("pc", {"memory_size": 50000, "img_size": 512}, 0.95),
        _s("pc", {"memory_size": 100000, "img_size": 512}, 0.96),
    ]
    axes = {a.axis: a for a in summarize_trends(samples, "image_auroc")[0].axes}
    assert axes["memory_size"].points == ((50000.0, 0.95), (100000.0, 0.96))
    assert axes["memory_size"].direction == "increasing"
