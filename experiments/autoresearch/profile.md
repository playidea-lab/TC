# Profile: autoresearch-nanochat (카파시 autoresearch / nanochat LLM 사전학습)

> explore-loop QD 엔진의 헤드라인 도메인 프로파일. autoresearch의 hill-climb를 MAP-Elites로 교체한다.
> §프로파일 계약 8키 + 실행 바인딩 `scripts/profile_autoresearch_nanochat.py`.
> idea: `TheCommons/.cq/runtime/ideas/explore-loop-autoresearch-profile.md` (AR1~AR10).

## primary_metric
- `score` = **`-val_bpb`** (val bits-per-byte의 부호 반전). **mode=max** (컨트롤러 max 전제 → 어댑터가 반전).
  낮은 bpb일수록 높은 score. bpb는 데이터 엔트로피 하한이 있으나 5분 예산에선 포화 안 함.

## task (아카이브 비-recipe 맥락축)
- **단일 task `nanochat`** — autoresearch는 코퍼스 1개 고정(climbmix, prepare.py). mvtec의 category 같은
  맥락축이 없다. archive 키 = `(nanochat, size_bin, shape_bin)`. 단일-task 2D 격자(MAP-Elites 원전 형태).

## bd_axes (BD 격자 2축 — 실행 바인딩 `scripts/profile_autoresearch_nanochat.py`)
- **(size, shape)**. 둘 다 아키텍처 config에서 **실행 전 결정론 계산**(측정치 tokens/mfu/vram은 사전
  binning 불가 → 격자축 아님, describe.json 진단 메타로 로깅. idea Option C).
- `bin_rule`(RE2): genotype → `(size_bin, shape_bin)`.
  - **size_bin** = `clip(log10(num_params) - 6.5, 0, 4)`. `num_params`는 `build_model_config` +
    `num_scaling_params` 공식 미러(`num_params(depth, aspect_ratio)`, 검증: depth8·ar64 → 50.3M).
    보편 후보축(카파시 "depth12→24 전이" = 스케일 보편이 여기서 표면화).
  - **shape_bin** = `clip(log2(aspect_ratio) - 5, 0, 3)` (32→0,64→1,128→2,256→3). 깊이↔너비 비.
    negative-control 축(보편 안 나와야 알고리즘 정합).
- `mutate`(RE5 within 섭동): depth ×1.5(최소 +2)로 size↑, aspect_ratio 고정.
- `build_pool`: `(depth ∈ {4,6,8,12}) × (aspect_ratio ∈ {32,64,128})` 12 씨앗 → 6+ 셀 커버(검증됨).
- ⚠️ bin 경계는 **잠정** — P-setup 실주행서 num_params↔train.py 실제 출력 대조 + 경계 calibrate.

## data_layout
- `~/.cache/autoresearch/` (prepare.py가 1회 생성: climbmix 데이터 샤드 + BPE 토크나이저). 글로브 아님.
- **prepare.py는 고정 evaluator**(`evaluate_bpb` = ground truth). 수정 금지.
- VOCAB_SIZE=8192, MAX_SEQ_LEN=2048, TIME_BUDGET=300s (prepare.py 상수, profile_*.py와 동기화).

## recipe_catalog
```json
{
  "implemented": [
    {"recipe_id": "autoresearch-nanochat", "script": "experiments/autoresearch/train.py",
     "family": "gpt-muon", "axes": ["depth", "aspect_ratio"]}
  ],
  "candidates_to_author": [
    {"recipe_id": "nanochat-moe",     "family": "mixture-of-experts", "note": "MLP→MoE 라우팅"},
    {"recipe_id": "nanochat-gqa",     "family": "grouped-query-attn",  "note": "n_kv_head < n_head"},
    {"recipe_id": "nanochat-optim-x", "family": "optimizer-variant",   "note": "Muon→Lion/SOAP 등"}
  ]
}
```
- implemented는 vendored `train.py`(무수정 템플릿). within 변이는 상수 치환(materialize).
- cross-recipe(MoE/GQA/옵티마이저 교체)는 Tier2 에이전트 저술 — 단일 계열이라 AR10 보편은 ≥2 계열 추가 후.

## dispatch (cq_dispatch.py 인자 — profile이 build_command로 직접 지정)
- `--code-string` (materialize 변형 코드) + `--command` (build_command: PYTHONPATH=vendored + cu128).
- `--monitor score --metric score`. inject 없음(config는 코드에 baking).
- 워커: **NVIDIA GPU(H100급) 필수**. torch==2.9.1+cu128 · kernels>=0.11.7 · rustbpe · tiktoken.
- `--run-timeout`: 5분 예산 + 컴파일/평가 여유 (≈600s 권장).

## abstract_taxonomy (seed)
```json
{
  "capacity": ["autoresearch-nanochat.depth", "autoresearch-nanochat.num_params"],
  "shape":    ["autoresearch-nanochat.aspect_ratio"]
}
```
- 기대 1차 보편 후보: **size(num_params)↑ → score↑** 가 옵티마이저/아키텍처 계열 횡단 반복되는가
  (= 고정 5분 compute에서 compute-최적 능선). 단일 계열에선 미발동(≥2 계열 = candidates_to_author 후).

## code_convention (materialize 상수 치환 규약)
- 원본 `train.py`는 **무수정 템플릿**. `materialize(genotype, args)`가 모듈 상수를 라인-앵커 정규식으로
  치환(`^DEPTH\s*=.*$` → `DEPTH = <val>`). config 키→상수 매핑은 `_CONST`(depth→DEPTH, aspect_ratio→ASPECT_RATIO).
- 어댑터가 train.py 끝에 append: `@score=-val_bpb` emit + `describe.json`(best_value=score + 진단메타
  tokens/mfu/vram/num_steps) write(워크스페이스 cwd, pcq 불요 → 토큰 만료 무관).
- prepare.py import는 `PYTHONPATH=experiments/autoresearch`(build_command)로 해결.

## baseline (콜드스타트)
- `autoresearch-nanochat`, `{"depth": 8, "aspect_ratio": 64}` (원본 기본값, num_params 50.3M).

## §setup (P-setup — 사람 개입, 첫 실주행 전 1회)
1. **GPU 워커**: NVIDIA GPU에 autoresearch 환경 사전 워밍(torch cu128/kernels/rustbpe — uv 첫 설치가
   5분 예산 잠식하지 않도록 1회 캐시). `python -c "import torch; print(torch.cuda.is_available())"` True.
2. **데이터 캐시**: 워커에서 `uv run prepare.py` 1회 → `~/.cache/autoresearch/` 생성(cq_dispatch는
   train.py만 실행하므로 데이터 없으면 즉시 실패).
3. **`cq auth login`**(사람만) + worker active + `CQ_PROJECT_ID/CQ_WORKER_ID`.
4. **build_command 검증**: 워커 토폴로지(로컬 GPU vs 원격)에 따라 PYTHONPATH·파일 전달·env incantation을
   조정(잠정값). 원본 train.py 수동 1-run이 5분 내 요약블록 출력하는지 확인.

## 첫 실주행 (P-firstrun)
```
run_explore.py --profile autoresearch-nanochat --tasks nanochat --budget ~12 --epsilon 0.4 \
  --worker-id <GPU> --code-root ~/git/TheCommons \
  --state .cq/runtime/state/explore_loop_autoresearch_state.json --run-timeout 600
```
- 산출물: `(size × shape)` illumination map 1장. universal(AR10)은 단일 계열이라 미발동 예상(정상 — 목표는 지도).

## 기존 corpus 맥락
- 첫 외부 도메인 profile(mvtec 외 2번째) → explore-loop 엔진의 도메인-무관 주장 검증.
- vendored 원본: `TheCommons/experiments/autoresearch/` (upstream 228791f, MIT, 무수정 — NOTICE.md).
