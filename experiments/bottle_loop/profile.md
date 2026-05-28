# Profile: mvtec-ad (MVTec 이상탐지)

> explore-loop 엔진의 도메인 프로파일. §프로파일 계약(SKILL.md)의 8개 키를 채운다.
> 새 도메인은 이 파일을 본떠 `profiles/<name>.md`를 만들면 같은 엔진을 재사용한다.

## primary_metric
- `image_auroc` (image-level ROC-AUC, **높을수록 좋음**, mode=max).
- 포화 주의: 1.0(천장) 셀은 보편 방향 판정에서 noise 취급(직전 MVTec서 hazelnut/grid/transistor 포화).

## task (아카이브 비-recipe 맥락축)
- MVTec **category**. 비포화 우선 권장: `screw`, `pill`, `cable`(추세 방향이 noise에 안 묻힘).
- 포화 경향(천장 근처): `hazelnut`, `grid`, `transistor`, `zipper` — 보편 검증엔 부적합(참고용).
- task별로 독립 BD 격자(archive 키 = `(task, cap_bin, res_bin)`).

## bd_axes (BD 격자 2축 — 실행 바인딩 `scripts/profile_mvtec_ad.py`)
- **(capacity, resolution)**. 컨트롤러는 이 격자에서 select·place·universal을 돈다.
- `bin_rule`(RE2): genotype → `(capacity_bin, resolution_bin)`.
  - **capacity_bin**: recipe별 구체축을 공통 0~4 척도로 정규화 — patchcore.memory_size·padim.n_features·
    ae.latent_dim·fastflow.flow_steps는 log10+offset, efficientad.backbone(이산)은 small/medium/large→2/3/4.
    서로 다른 recipe가 같은 cap_bin에 떨어져 **지역 경쟁** → capacity↑→auroc↑ 보편을 map gradient로 직접검증.
  - **resolution_bin**: img_size 고정 경계(224/320/416/512). 모든 recipe 공통. 직전 실험서 비보편 →
    **negative control**(여기서 보편 안 나와야 알고리즘이 옳음).
- `mutate`(RE5 within 섭동): capacity 축만 1.5배(이산 backbone은 한 단계 위), resolution 유지.
- `build_pool`: implemented recipe × capacity 3변주 씨앗(컨트롤러 coverage 구동).
- ⚠️ 정규화 공식은 **잠정** — P4 실데이터서 bin 경계 calibrate(idea explore-loop-qd-rigor P4).

## data_layout
- root: `/Users/changmin/datasets/MVtec-ad/mvtec_anomaly_detection` (`--data-root`로 override).
- train: `{root}/{category}/train/good/*.png`
- test : `{root}/{category}/test/*/*.png` — label: `/good/` → 0(정상), else 1(이상).

## recipe_catalog
```json
{
  "implemented": [
    {"recipe_id": "mvtec-patchcore",   "script": "experiments/bottle_loop/train_patchcore.py",   "family": "feature-memory",   "axes": ["memory_size", "img_size", "backbone"]},
    {"recipe_id": "mvtec-efficientad", "script": "experiments/bottle_loop/train_efficientad.py", "family": "student-teacher", "axes": ["backbone", "epochs", "learning_rate", "img_size"]},
    {"recipe_id": "mvtec-autoencoder", "script": "experiments/bottle_loop/train_ae.py",          "family": "reconstruction", "axes": ["latent_dim", "epochs", "img_size"]}
  ],
  "candidates_to_author": [
    {"recipe_id": "mvtec-padim",    "family": "gaussian-feature", "capacity_axis": "n_features", "note": "patch feature 다변량 가우시안 fit, Mahalanobis 거리"},
    {"recipe_id": "mvtec-fastflow", "family": "normalizing-flow", "capacity_axis": "flow_steps", "note": "feature에 2D normalizing flow, likelihood"},
    {"recipe_id": "mvtec-patchsvdd","family": "one-class",        "capacity_axis": "embed_dim",  "note": "patch-level deep SVDD"}
  ]
}
```

## dispatch (cq_dispatch.py 인자)
- inject 키: `{"category": "<task>", ...recipe config...}` (예: `{"category":"screw","img_size":384,"memory_size":50000,"backbone":"wide_resnet50_2","batch_size":4}`)
  - ※ `data_root`는 cq_dispatch가 `--data-root`로 env(DATA_ROOT)+cfg.data_root에 자동 주입 — inject에 적지 말 것.
- `--monitor image_auroc --metric image_auroc`
- `--req torch --req torchvision --req scikit-learn --req pillow --req numpy`
- `--run-timeout 1800`

## abstract_taxonomy (seed — 에이전트가 확장 가능)
```json
{
  "capacity":     ["mvtec-patchcore.memory_size", "mvtec-efficientad.backbone", "mvtec-autoencoder.latent_dim", "mvtec-padim.n_features", "mvtec-fastflow.flow_steps"],
  "resolution":   ["*.img_size"],
  "train_amount": ["mvtec-efficientad.epochs", "mvtec-autoencoder.epochs"]
}
```
- 새 recipe의 축이 기존 범주에 안 맞으면 에이전트가 새 범주 신설(예: flow_steps를 capacity로 볼지 별도 범주로 볼지 판단).
- 기대 1차 보편 후보: **capacity↑ → image_auroc↑** 가 feature-memory·reconstruction·student-teacher 횡단 반복되는가.

## code_convention (새 recipe train.py 저술 시)
본보기: `experiments/bottle_loop/train_patchcore.py`
- `cfg = pcq.config()` → `cfg.get("category"/"img_size"/...)`로 주입 config 읽기.
- 데이터: 위 data_layout. ImageNet 정규화(mean/std), device `mps` 우선.
- 메트릭: `print(f"@image_auroc={auroc:.4f}", flush=True)` (cq MetricWriter가 stdout 파싱).
- `pcq.log_config(...effective...)` → `save_metrics/save_run_summary/save_manifest/finalize_run`.
- `describe.json` = `describe_run(out).to_dict()`를 `pcq.output_dir()`에 저장.

## baseline (콜드스타트)
- `mvtec-patchcore`, `{"img_size": 384, "memory_size": 50000, "backbone": "wide_resnet50_2", "batch_size": 4}`.

## 기존 corpus 맥락
- 직전 MVTec 일반화([[mvtec-generalization-3h-plan]]): patchcore 단일 18라운드. memory_size↑=보편(비포화),
  img_size↑=비보편. evidence `ev-gen-{cat}-r{N}-...`. 이 프로파일의 첫 run은 그 위에 efficientad/ae를 얹어
  cross-recipe capacity 보편을 본다.
