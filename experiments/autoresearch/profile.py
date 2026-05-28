"""autoresearch-nanochat 프로파일의 실행 바인딩 — 카파시 autoresearch를 explore-loop QD 엔진에 연결.

profiles/autoresearch-nanochat.md(사람이 읽는 §프로파일 계약)와 짝이 되는 **실행 코드**다.
mvtec(자체완결 pcq 스크립트)과 달리 autoresearch는 (a) train.py가 모듈 상수(DEPTH 등) 하드코딩이고
(b) prepare.py(고정 evaluator)에 의존하며 (c) cu128 torch+kernels 환경이 필요하다. 그래서:

- **materialize(g, args)**: 원본 train.py를 *읽기만* 하고 상수(DEPTH·ASPECT_RATIO)를 genotype config로
  치환한 *변형 코드 문자열*을 만든다(+ @score emit + describe.json write 코드 append). 원본 불변.
- **build_command(action, args)**: PYTHONPATH=vendored 디렉토리(prepare.py import)로 워커 command 지정.
- BD 격자 = (size, shape). size=num_params(아키텍처 config서 사전 계산), shape=aspect_ratio.
  ★ idea explore-loop-autoresearch-profile의 Option C — tokens/mfu/vram은 격자축이 아니라 describe.json
  진단 메타로 로깅(고정 5분 예산이라 측정치는 사전 binning 불가).

⚠️ bin 경계·build_command env incantation은 **잠정** — P-setup 워커에서 실데이터로 calibrate/validate.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from the_commons.exploration.map_elites import Genotype

# --- run_explore 계약 (엔진이 소비하는 profile 속성/함수) ---------------------
TEMPLATE_REL = "experiments/autoresearch/train.py"   # vendored 원본(무수정 템플릿), --code-root 기준
RECIPE_SCRIPT: dict[str, str] = {"autoresearch-nanochat": TEMPLATE_REL}
RECIPE_CATALOG = {"implemented": [{"recipe_id": "autoresearch-nanochat"}]}
# autoresearch는 cu128 torch + custom kernels + rustbpe. mvtec식 --with 자체완결 설치가 어려워
# build_command가 직접 command를 지정한다(REQS는 참고용; build_command가 우선).
REQS = ["numpy", "pyarrow", "requests", "tiktoken"]
MONITOR = "score"   # = -val_bpb (컨트롤러 max 전제 → 부호 반전). 낮은 bpb일수록 높은 score.
METRIC = "score"
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"   # 공식 pytorch cu128 wheel index

# 데이터 상수(prepare.py와 일치 — 사전 num_params 계산용). prepare.py 수정 시 동기화.
VOCAB_SIZE = 8192
HEAD_DIM = 128

# BD 격자
SIZE_BINS = 5
SHAPE_BINS = 4
# genotype config 키 → train.py 모듈 상수명 (materialize 치환 대상). 확장 가능.
_CONST: dict[str, str] = {"depth": "DEPTH", "aspect_ratio": "ASPECT_RATIO"}


def _clip(v: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(round(v))))


def num_params(depth: int, aspect_ratio: int) -> int:
    """train.py의 GPT 파라미터 수를 config에서 사전 계산(미러). build_model_config +
    num_scaling_params 공식 그대로. depth=8·ar=64 → 50.3M (program.md와 일치, 검증됨)."""
    n_embd = ((depth * aspect_ratio + HEAD_DIM - 1) // HEAD_DIM) * HEAD_DIM
    n_head = n_embd // HEAD_DIM
    n_ve = sum(1 for i in range(depth) if i % 2 == (depth - 1) % 2)  # has_ve 레이어 수
    wte = VOCAB_SIZE * n_embd
    lm_head = VOCAB_SIZE * n_embd
    value_embeds = n_ve * VOCAB_SIZE * n_embd          # kv_dim == n_embd (n_kv_head=n_head)
    transformer = depth * 12 * n_embd * n_embd + n_ve * 32 * n_head  # attn4+mlp8=12·d² (+ve_gate)
    scalars = 2 * depth
    return wte + lm_head + value_embeds + transformer + scalars


def size_bin(g: Genotype) -> int:
    """num_params(사전계산) → log10 정규화 0~4. ★offset 잠정(P-setup calibrate)."""
    cfg = g.as_dict()
    depth = int(cfg.get("depth", 8))
    ar = int(cfg.get("aspect_ratio", 64))
    return _clip(math.log10(num_params(depth, ar)) - 6.5, 0, SIZE_BINS - 1)


def shape_bin(g: Genotype) -> int:
    """aspect_ratio(깊이↔너비 비) → log2 bin. negative-control 후보축(보편 안 나와야 정상)."""
    ar = float(g.as_dict().get("aspect_ratio", 64))
    return _clip(math.log2(max(ar, 1.0)) - 5, 0, SHAPE_BINS - 1)   # 32→0,64→1,128→2,256→3


def bin_rule(g: Genotype) -> tuple[int, int]:
    return size_bin(g), shape_bin(g)


def mutate(g: Genotype) -> Genotype:
    """within 섭동(RE5) — size 축만 키운다(depth↑ ×1.5, 최소 +2). shape(aspect_ratio) 고정."""
    cfg = g.as_dict()
    depth = int(cfg.get("depth", 8))
    cfg["depth"] = float(max(depth + 2, round(depth * 1.5)))
    return Genotype.of(g.recipe, {k: float(v) for k, v in cfg.items()})


# 씨앗 격자 — (depth × aspect_ratio). size·shape 두 축에 펼쳐 컨트롤러 coverage 구동.
_DEPTH_SEEDS = [4, 6, 8, 12]
_AR_SEEDS = [32, 64, 128]


def build_pool(tasks: list[str], catalog: dict) -> dict[str, list[Genotype]]:
    """(depth × aspect_ratio) 격자 씨앗. task는 단일('nanochat') — autoresearch는 코퍼스 1개 고정."""
    pool: dict[str, list[Genotype]] = {}
    for task in tasks:
        genos = [Genotype.of("autoresearch-nanochat",
                             {"depth": float(d), "aspect_ratio": float(ar)})
                 for d in _DEPTH_SEEDS for ar in _AR_SEEDS]
        pool[task] = genos
    return pool


def recipe_arg(recipe: str) -> str:
    return "nanochat"


def build_inject(action) -> dict:
    """autoresearch는 config를 코드에 baking(materialize)하므로 cq_config 주입 없음."""
    return {}


# materialize가 train.py 끝에 append하는 어댑터 코드 — @score emit + describe.json write.
# train.py 말미 변수(val_bpb·num_params·total_tokens·peak_vram_mb·steady_state_mfu·step·DEPTH·
# ASPECT_RATIO)를 참조한다. describe.json은 cwd(워크스페이스)에 쓰여 cq_dispatch가 회수(토큰 무관).
_ADAPTER = '''
# --- explore-loop adapter (auto-appended; 원본 train.py 무수정) ---
import json as _json
_score = -float(val_bpb)
print(f"@score={_score:.6f}", flush=True)
with open("describe.json", "w") as _f:
    _json.dump({
        "best_value": _score, "primary_metric": "score",
        "val_bpb": float(val_bpb), "num_params_M": num_params / 1e6,
        "depth": DEPTH, "aspect_ratio": ASPECT_RATIO,
        "total_tokens_M": total_tokens / 1e6, "peak_vram_mb": float(peak_vram_mb),
        "mfu_percent": float(steady_state_mfu), "num_steps": int(step),
    }, _f)
'''


def materialize(genotype: Genotype, args) -> str:
    """원본 train.py(무수정 템플릿)를 읽어 genotype 상수를 치환한 변형 코드 문자열을 만든다."""
    template = Path(args.code_root) / TEMPLATE_REL
    code = template.read_text(encoding="utf-8")
    for key, val in genotype.as_dict().items():
        const = _CONST.get(key)
        if const is None:
            continue
        # 모듈-레벨 상수 대입 라인을 통째로 치환(라인 앵커). 정수 상수만(DEPTH/ASPECT_RATIO).
        code = re.sub(rf"^{const}\s*=.*$", f"{const} = {int(val)}", code, count=1, flags=re.MULTILINE)
    return code + _ADAPTER


def build_command(action, args) -> str:
    """워커 실행 command — PYTHONPATH로 vendored prepare.py import + cu128 torch/kernels.
    ⚠️ env incantation은 잠정. P-setup 워커에서 검증·조정(워커 토폴로지/사전설치에 따라 다름)."""
    vendored = f"{args.code_root}/experiments/autoresearch"
    with_flags = ("--with 'torch==2.9.1' --with 'kernels>=0.11.7' --with rustbpe "
                  "--with tiktoken --with numpy --with pyarrow --with requests")
    return ('export PATH="/usr/local/bin:$HOME/.local/bin:$PATH" '
            f'&& export PYTHONPATH={vendored} '
            f'&& uv run --no-project {with_flags} --index-url {TORCH_INDEX} '
            'python -u train.py 2> train_err.log')
