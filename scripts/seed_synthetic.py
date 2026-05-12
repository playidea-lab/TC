"""부트스트랩 스크립트 — LLM oracle을 호출해 tabular cluster를 채운다.

실행: `uv run python scripts/seed_synthetic.py`

v0.1은 *수동 트리거* 가정. 자동화·재생성 정책은 v0.2 cycle.
"""

import logging
from itertools import product

from the_commons.seed.recipe_catalog import all_recipes
from the_commons.seed.synthetic_generator import (
    SeedSpec,
    SyntheticOracle,
    generate_seed_records,
)
from the_commons.settings import settings

logger = logging.getLogger(__name__)

# v0.1 — tabular 청중에 한정. 다른 modality는 v0.2.
MODALITIES = ["tabular"]
SAMPLE_BANDS = ["100-1k", "1k-10k", "10k-100k", "100k-1M"]
GOALS = ["baseline_reproduction", "sota_challenge", "exploration"]


def enumerate_specs() -> list[SeedSpec]:
    """catalog × band × goal 조합의 cartesian product."""
    specs: list[SeedSpec] = []
    recipes = all_recipes()
    for modality, band, goal, recipe in product(
        MODALITIES, SAMPLE_BANDS, GOALS, recipes
    ):
        specs.append(
            SeedSpec(
                modality=modality,
                sample_count_band=band,
                intent_goal=goal,
                recipe_id=recipe["recipe_id"],
                framework=recipe["framework"],
            )
        )
    return specs


async def run(oracle: SyntheticOracle) -> int:
    """oracle을 사용해 spec 전체를 synthetic record로 변환. 생성된 건수 반환."""
    specs = enumerate_specs()
    logger.info("synthetic seed plan: %d specs", len(specs))
    records = await generate_seed_records(
        oracle, specs, source_model=settings.gemini_reranker_model
    )
    logger.info("synthetic seed produced: %d records", len(records))
    # 실제 deposit은 /ingest endpoint 호출 또는 별도 batch insert로.
    # 이 스크립트는 record 생성까지만 책임.
    return len(records)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    # production oracle은 Gemini Flash 호출. 이 자리는 사용자가 직접 wiring.
    raise SystemExit(
        "production oracle wiring 필요. "
        "GeminiSyntheticOracle 구현 후 run(oracle)을 호출하세요."
    )
