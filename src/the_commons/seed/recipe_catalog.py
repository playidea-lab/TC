"""v0.1 recipe catalog — tabular 청중을 위한 정적 정의.

LLM 초안 + PI Lab 검증된 first-pass catalog. DB recipe 테이블에 INSERT.
이후 매치메이커는 catalog 외 recipe도 LLM-generator로 제안 가능 (open-ended).
"""

from typing import Any

# v0.1 tabular vertical slice — 5개 핵심 recipe
TABULAR_RECIPES: list[dict[str, Any]] = [
    {
        "recipe_id": "lightgbm",
        "family": "gradient_boosting",
        "framework": "lightgbm",
        "description": (
            "LightGBM — gradient boosting on histograms. Strong tabular baseline, "
            "fast on medium-to-large datasets, native categorical support."
        ),
        "metadata": {
            "hyperparam_ranges": {
                "num_leaves": [15, 31, 63, 127],
                "learning_rate": [0.01, 0.05, 0.1],
                "n_estimators": [100, 300, 500, 1000],
            },
            "expected_runtime_sec_band": {
                "10k-100k": [30, 300],
                "100k-1M": [120, 1200],
            },
            "strengths": ["tabular", "binary", "regression", "imbalanced"],
            "weaknesses": ["very_small_data"],
        },
        "source": "pilab",
        "verified": True,
    },
    {
        "recipe_id": "xgboost",
        "family": "gradient_boosting",
        "framework": "xgboost",
        "description": (
            "XGBoost — competitive boosting. Slightly slower than LightGBM on large "
            "data, often near-identical accuracy."
        ),
        "metadata": {
            "hyperparam_ranges": {
                "max_depth": [4, 6, 8],
                "learning_rate": [0.01, 0.05, 0.1],
                "n_estimators": [100, 300, 500, 1000],
            },
            "strengths": ["tabular", "binary", "multiclass"],
            "weaknesses": ["very_small_data"],
        },
        "source": "pilab",
        "verified": True,
    },
    {
        "recipe_id": "tabpfn",
        "family": "transformer",
        "framework": "tabpfn",
        "description": (
            "TabPFN — prior-fitted transformer for small tabular. Strong on "
            "<10k rows, often beats GBMs in that regime."
        ),
        "metadata": {
            "hyperparam_ranges": {},
            "expected_runtime_sec_band": {"1k-10k": [5, 60]},
            "strengths": ["small_tabular", "binary", "multiclass"],
            "weaknesses": ["large_data", "regression"],
        },
        "source": "pilab",
        "verified": True,
    },
    {
        "recipe_id": "sklearn-rf",
        "family": "bagging",
        "framework": "sklearn",
        "description": (
            "Random Forest — strong baseline that rarely fails. Slower training but "
            "robust to hyperparameter choice."
        ),
        "metadata": {
            "hyperparam_ranges": {
                "n_estimators": [100, 200, 500],
                "max_depth": [None, 10, 20],
            },
            "strengths": ["tabular", "robust"],
            "weaknesses": ["large_data_slow"],
        },
        "source": "pilab",
        "verified": True,
    },
    {
        "recipe_id": "logistic-regression",
        "family": "linear",
        "framework": "sklearn",
        "description": (
            "Logistic Regression — interpretable linear baseline. Always include as "
            "sanity check; if a complex model barely beats LR, it may not be worth it."
        ),
        "metadata": {
            "hyperparam_ranges": {
                "C": [0.01, 0.1, 1.0, 10.0],
            },
            "strengths": ["interpretable", "fast", "baseline"],
            "weaknesses": ["non_linear_data"],
        },
        "source": "pilab",
        "verified": True,
    },
]


def all_recipes() -> list[dict[str, Any]]:
    """v0.1 catalog 전체. M0~M5 단계에선 변경 불가능 (frozen list)."""
    return [dict(r) for r in TABULAR_RECIPES]
