"""mvtec-ad 프로파일의 실행 바인딩 — map_elites 컨트롤러에 주입하는 BD/섭동/후보.

profiles/mvtec-ad.md(사람이 읽는 §프로파일 계약)와 짝이 되는 **실행 코드**다. RE2(객관 binning)·
RE5(섭동 축)를 코드로 고정해 에이전트 주관 매핑을 제거한다. 컨트롤러는 도메인을 모르고, 이 모듈이
recipe별 구체축을 추상 BD축(capacity × resolution)으로 정규화한다.

BD 축(bd_axes): (capacity, resolution).
  - capacity: recipe마다 다른 구체축(memory_size·n_features·latent_dim·flow_steps·backbone)을
    log10 정규화 + recipe별 offset으로 같은 0~4 척도에. ★공식은 잠정 — P4 실데이터서 calibrate.
  - resolution: img_size(모든 recipe 공통) → 고정 bin. 직전 실험서 비보편이라 negative control.

⚠️ 정규화 공식은 명시적(감사 가능)이되 완벽한 cross-recipe 비교는 불가능하다 — 이것이 idea의
D비판 #4를 "주관"에서 "명시 규칙"으로 옮긴 것이다. P4 재검증서 bin 경계를 데이터로 보정한다.
"""

from __future__ import annotations

import math

from the_commons.exploration.map_elites import Genotype

# --- run_explore 계약 (엔진이 소비하는 profile 속성/함수) ---------------------
# recipe_id → train.py 상대경로(--code-root 기준). 정적 파일 디스패치(mvtec=자체완결 pcq 스크립트).
RECIPE_SCRIPT: dict[str, str] = {
    "mvtec-patchcore": "experiments/bottle_loop/train_patchcore.py",
    "mvtec-padim": "experiments/bottle_loop/train_padim.py",
    "mvtec-autoencoder": "experiments/bottle_loop/train_ae.py",
}
REQS = ["torch", "torchvision", "scikit-learn", "pillow", "numpy"]
RECIPE_CATALOG = {"implemented": [{"recipe_id": r} for r in RECIPE_SCRIPT]}
MONITOR = "image_auroc"   # cq best 판정 metric (높을수록 좋음)
METRIC = "image_auroc"    # 회수 metric 키


def recipe_arg(recipe: str) -> str:
    """cq job 이름 prefix — mvtec- 접두사 제거."""
    return recipe.replace("mvtec-", "")


def build_inject(action) -> dict:
    """cq_config.json에 주입할 next_config — pcq.config()가 읽는다. category=task + seed + config."""
    return {"category": action.task, "seed": int(action.seed), **action.genotype.as_dict()}


CAP_BINS = 5
RES_BINS = 5

# recipe_id → (capacity config 키, log10 raw에 더할 offset) — 잠정 정규화(P4 calibrate)
# offset은 각 recipe의 전형 capacity 범위를 0~4 척도 중앙(≈2)에 맞추기 위한 것.
_CAPACITY: dict[str, tuple[str, float]] = {
    "mvtec-patchcore": ("memory_size", -2.0),   # 1e2~1e6 → log 2~6, -2 → 0~4
    "mvtec-padim": ("n_features", 0.0),         # 1e0~1e4 → log 0~4
    "mvtec-autoencoder": ("latent_dim", 0.0),   # 1e0~1e4
    "mvtec-fastflow": ("flow_steps", 1.0),      # 1e0~1e3 → +1 → 1~4
}

# efficientad backbone(이산 capacity 축) → bin 직접 매핑
_BACKBONE_CAP: dict[str, int] = {"small": 2, "medium": 3, "large": 4}

# img_size → resolution bin (공통 축)
_RES_EDGES = (224, 320, 416, 512)               # < → 0, …, >= 512 → 4


def _clip(v: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(round(v))))


def capacity_bin(g: Genotype) -> int:
    """recipe별 구체 capacity 축을 공통 0~4 척도로 정규화(RE2)."""
    cfg = g.as_dict()
    if g.recipe == "mvtec-efficientad":
        bb = str(cfg.get("backbone", "small"))
        return _BACKBONE_CAP.get(bb, 2)
    spec = _CAPACITY.get(g.recipe)
    if spec is None:
        return 0
    key, offset = spec
    raw = float(cfg.get(key, 1.0))
    return _clip(math.log10(max(raw, 1.0)) + offset, 0, CAP_BINS - 1)


def resolution_bin(g: Genotype) -> int:
    """img_size → resolution bin(모든 recipe 공통). negative-control 축."""
    img = float(g.as_dict().get("img_size", 256))
    return sum(1 for edge in _RES_EDGES if img >= edge)


def bin_rule(g: Genotype) -> tuple[int, int]:
    return capacity_bin(g), resolution_bin(g)


def mutate(g: Genotype) -> Genotype:
    """within-recipe 섭동(RE5) — capacity 축만 키운다(resolution 고정)."""
    cfg = g.as_dict()
    if g.recipe == "mvtec-efficientad":           # 이산: backbone 한 단계 위
        order = ["small", "medium", "large"]
        cur = str(cfg.get("backbone", "small"))
        i = order.index(cur) if cur in order else 0
        cfg["backbone"] = order[min(i + 1, len(order) - 1)]
        return Genotype.of(g.recipe, _numeric_only(cfg))
    spec = _CAPACITY.get(g.recipe)
    if spec is not None:
        key, _ = spec
        cfg[key] = round(float(cfg.get(key, 1.0)) * 1.5, 3)
    return Genotype.of(g.recipe, _numeric_only(cfg))


def _numeric_only(cfg: dict) -> dict[str, float]:
    """Genotype.config는 수치 튜플 가정 — 이산값(backbone)은 capacity_bin으로 흡수되므로
    genotype 식별엔 수치 축만 남긴다(이산은 별도 키로 보존하지 않고 bin이 대표)."""
    return {k: float(v) for k, v in cfg.items() if isinstance(v, (int, float))}


# capacity 씨앗 — recipe별로 cap_bin 1~3·2~4 등 3 bin에 펼쳐지도록(P4 calibrate)
_CAP_SEEDS: dict[str, list[float]] = {
    "mvtec-patchcore": [1000, 10000, 100000],    # cap 1,2,3
    "mvtec-padim": [50, 500, 5000],              # cap 2,3,4
    "mvtec-autoencoder": [16, 128, 512],         # cap 1,2,3 (latent ≤512 — 비용 cap)
}
# resolution 변주(negative control 축) — img_size bin. ae는 학습 비용이 커서 256만(결함5).
_IMG_DEFAULT = [256.0, 384.0]                     # res_bin 1, 2
_IMG_BY_RECIPE: dict[str, list[float]] = {"mvtec-autoencoder": [256.0]}


def build_pool(tasks: list[str], catalog: dict) -> dict[str, list[Genotype]]:
    """recipe_catalog.implemented에서 Tier1 후보 genotype 격자를 생성.
    capacity × resolution 두 축을 변주해 빈 bin을 채울 씨앗을 만든다(컨트롤러 coverage 구동).
    ae는 학습 비용이 커 epochs 5·img 256으로 cap(결함5 — latent 1000+epochs 10이 32분)."""
    pool: dict[str, list[Genotype]] = {}
    for task in tasks:
        genos: list[Genotype] = []
        for item in catalog.get("implemented", []):
            rid = item["recipe_id"]
            spec = _CAPACITY.get(rid)
            if spec is None:
                continue
            key, _ = spec
            extra = {"epochs": 5.0} if rid == "mvtec-autoencoder" else {}
            for raw in _CAP_SEEDS.get(rid, [100, 1000]):
                for img in _IMG_BY_RECIPE.get(rid, _IMG_DEFAULT):
                    genos.append(Genotype.of(rid, {key: float(raw), "img_size": img, **extra}))
        pool[task] = genos
    return pool
