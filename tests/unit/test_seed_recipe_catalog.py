"""v0.1 recipe catalog 정합성 검증."""

import pytest

from the_commons.seed.recipe_catalog import TABULAR_RECIPES, all_recipes


def test_catalog_has_five_recipes() -> None:
    """v0.1은 5개 핵심 recipe."""
    assert len(TABULAR_RECIPES) == 5


def test_recipe_ids_are_unique() -> None:
    ids = {r["recipe_id"] for r in TABULAR_RECIPES}
    assert len(ids) == 5


def test_all_recipes_returns_copy() -> None:
    """all_recipes()는 shallow copy를 반환해 caller가 catalog 변경 못 함."""
    a = all_recipes()
    b = all_recipes()
    a[0]["recipe_id"] = "tampered"
    assert b[0]["recipe_id"] != "tampered"


@pytest.mark.parametrize("recipe", TABULAR_RECIPES)
def test_recipe_has_required_fields(recipe: dict) -> None:
    """각 recipe entry는 DB schema에 필요한 필드 모두 보유."""
    for field in ("recipe_id", "family", "framework", "description", "metadata"):
        assert field in recipe, f"{recipe['recipe_id']}: {field} 누락"
    assert isinstance(recipe["metadata"], dict)


def test_all_recipes_target_tabular_modality() -> None:
    """v0.1 catalog는 tabular 한정 — strengths에 'tabular' 또는 'small_tabular' 포함."""
    tabular_keywords = {"tabular", "small_tabular", "baseline", "interpretable", "robust"}
    for recipe in TABULAR_RECIPES:
        strengths = set(recipe["metadata"].get("strengths", []))
        assert (
            strengths & tabular_keywords
        ), f"{recipe['recipe_id']}: tabular 관련 강점 누락"


def test_lightgbm_and_xgboost_are_in_catalog() -> None:
    """가장 핵심적인 두 보ost가 catalog에 있어야 매치메이커가 효과적."""
    ids = {r["recipe_id"] for r in TABULAR_RECIPES}
    assert "lightgbm" in ids
    assert "xgboost" in ids
