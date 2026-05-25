"""evidence(dict) → trends.Sample 어댑터 테스트.

적재된 evidence(pcq_record.config = {recipe_id, **hyperparams}, metrics)를 귀납 계산
입력으로 변환한다. trends는 형태 무관 순수 함수, 어댑터만 evidence 구조를 안다.
"""

from the_commons.knowledge.adapter import evidence_to_sample


def test_evidence_to_sample_extracts_recipe_config_metrics():
    ev = {
        "evidence_id": "ev-x",
        "pcq_record": {
            "config": {
                "recipe_id": "mvtec-patchcore",
                "memory_size": 50000,
                "img_size": 384,
                "backbone": "wide_resnet50_2",
            },
            "metrics": {"image_auroc": 0.91, "train_loss": 0.01},
        },
    }
    assert evidence_to_sample(ev) == (
        "mvtec-patchcore",
        {"memory_size": 50000, "img_size": 384, "backbone": "wide_resnet50_2"},
        {"image_auroc": 0.91, "train_loss": 0.01},
    )


def test_evidence_to_sample_none_when_no_recipe_id():
    ev = {"pcq_record": {"config": {"memory_size": 1}, "metrics": {}}}
    assert evidence_to_sample(ev) is None


def test_evidence_to_sample_none_on_empty():
    assert evidence_to_sample({}) is None


def test_evidence_to_sample_feeds_summarize_trends():
    # 어댑터 → summarize_trends 통합: evidence 리스트가 추세로 정제된다
    from the_commons.knowledge.trends import summarize_trends

    evs = [
        {
            "pcq_record": {
                "config": {"recipe_id": "pc", "memory_size": 10000},
                "metrics": {"image_auroc": 0.74},
            }
        },
        {
            "pcq_record": {
                "config": {"recipe_id": "pc", "memory_size": 50000},
                "metrics": {"image_auroc": 0.91},
            }
        },
        {
            "pcq_record": {
                "config": {"recipe_id": "pc", "memory_size": 100000},
                "metrics": {"image_auroc": 0.96},
            }
        },
    ]
    samples = [s for ev in evs if (s := evidence_to_sample(ev))]
    axes = {a.axis: a for a in summarize_trends(samples, "image_auroc")[0].axes}
    assert axes["memory_size"].direction == "increasing"
