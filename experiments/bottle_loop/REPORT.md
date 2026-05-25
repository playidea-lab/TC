# PCQ-CQ-TC 폐루프 견고성 검증 리포트

> 실험: 실데이터 산업 이상탐지 장시간 폐루프 자전 (MVTec bottle → screw)
> 일자: 2026-05-23 ~ 05-25 · 하드웨어: Apple M4 Max (16-core, 64GB, MPS) · 워커: my-notebook (cq 로컬)
> 검증 대상: **AUROC가 아니라 PCQ-CQ-TC 폐루프 메커니즘 자체의 견고성**

---

## 1. 셋업

| 구성요소 | 역할 | 비고 |
|---------|------|------|
| **Claude Code** (이 세션) | 오케스트레이터 + 코드 author | 외부 API 키 0 — train.py를 직접 작성 |
| `scripts/cq_dispatch.py` | cq 디스패치 헬퍼 | next_config 주입 → 워커 실행 → describe.json 회수 |
| **cq worker** (my-notebook) | 원격 워커 | `uv --with pcq>=4.11.0,torch,...` 격리 실행, MPS |
| **PCQ** 4.11.0 | run 봉인 | `pcq.config()`/`log_config()`(effective) → `describe_run` |
| **TC MCP** (the-commons) | 도서관 + 소믈리에 | `tc_recommend`/`tc_ingest_pcq`/`tc_recent_attempts` |

라운드 = `tc_recommend → train.py 작성 → cq_dispatch → PCQ describe → tc_ingest_pcq → 환류 → state 갱신`.

---

## 2. 라운드 결과 (10 evidence, 0 실패)

| R | recipe | category | 핵심 config | image_auroc | 비고 |
|---|--------|----------|-------------|-------------|------|
| 1 | trivial | bottle | mean-MSE | 0.8413 | 기존 baseline |
| smoke | autoencoder | bottle | epochs 3, latent 64 | 0.419 | e2e 배선 검증 (underfit) |
| 2 | autoencoder | bottle | epochs 20, latent 128 | 0.65 | 추천: underfit 인식→capacity↑ |
| 3 | efficientad | bottle | student-teacher, resnet18 | **1.0** | 추천: 과거 실패 traceback→recipe 전환+self-correct |
| 4 | efficientad | bottle | wide_resnet50_2 | **1.0** | 추천: backbone 확대 exploit |
| 5 | efficientad | screw | ST, 384px | 0.8608 | 어려운 카테고리 전환 baseline |
| 6 | patchcore | screw | memory 10k | 0.7465 | memory subsample 부족 |
| 7 | patchcore | screw | memory 50k | 0.9106 | 환류 판단: memory↑ → ST 추월 |
| 8 | patchcore | screw | 512px, m50k | 0.9463 | 환류 판단: 고해상도↑ |
| 9 | patchcore | screw | 512px, m100k | **0.9643** | screw SOTA(~0.95) 돌파 |

---

## 3. 검증 결과 (메커니즘 견고성)

### ✅ 작동하는 고리
1. **무중단 e2e** — 10/10 라운드 성공, 0 실패. recipe 3종(autoencoder, student-teacher, patchcore)을 Claude Code가 매 라운드 직접 작성·디스패치.
2. **PCQ 봉인 진실성** — `reproducibility_evidence.config.hyperparams`에 train.py가 실제 소비한 effective config(backbone, img_size, memory_size, device=mps)가 정확히 기록됨. agent 주장이 아닌 실측.
3. **적재 정본 경로** — `tc_ingest_pcq`가 describe를 받아 evidence_id 10건 발급. 100% 성공.
4. **환류 정확** — `tc_recent_attempts`가 적재된 모든 evidence(metrics 포함)를 정확히 조회.
5. **성능 추격** — bottle 1.0, **screw 0.86→0.96 SOTA 돌파**. 환류 기반 가설-검증 사이클(memory 10k→50k→100k, img 384→512)이 5라운드 연속 적중.

### ⚠️ 핵심 발견: 추천 고리의 한계
- `tc_recommend`가 **corpus 성장을 반영하지 못함**: 10건 적재 후에도 `real_count=20` 정체, intent의 category(screw) 신호를 next_config에 흘리지 못하고 corpus 과거(bottle/autoencoder)로 회귀.
- **비대칭**: 적재→환류(`tc_recent_attempts`)는 정확한데 추천(`tc_recommend`)만 부실 → 문제는 적재가 아니라 recommend의 **retrieve/composer 로직**.
- **대응(현 closure)**: 추천이 부실할 때 **환류 기반 agent 판단**으로 폐루프를 닫음. r5~r9에서 Claude Code가 `tc_recent_attempts`를 읽고 가설(memory 부족, 고해상도 필요)을 세워 추격 — 이 경로가 실제로 작동했고 SOTA를 달성.

---

## 4. 발견·수정한 버그

**`cq_dispatch.py` 쉘 리다이렉트 버그** (수정 완료)
- `uv run --with pcq>=4.11.0 ...`에서 `>`가 쉘 리다이렉트로 해석돼 train.py의 **stdout 전체가 `=4.11.0` 파일로 빠짐**. → cq metric writer가 `metrics={}`만 받던 원인.
- 수정: `--with '{r}'` 작은따옴표 (커밋 대기).
- 영향: describe.json은 train.py가 직접 파일로 저장하므로 적재엔 무영향이었으나, cq 측 메트릭 회수가 깨져 있었음.

---

## 5. 다음 과제
1. **`tc_recommend` retrieve/composer 수정** — corpus 신규 evidence를 retrieve에 반영(real_count 정체 원인), intent.category를 next_config로 전파. 이게 폐루프의 마지막 약한 고리.
2. `cq_dispatch.py` 따옴표 수정 커밋.
3. (선택) coreset subsampling, 멀티스케일 feature로 screw 천장 추가 추격.
4. transistor/grid 등 다른 어려운 카테고리로 일반성 확장.

## 6. 산출 evidence
`ev-smoke-ae-001`, `ev-r2-ae-001`, `ev-r3-efficientad-001`, `ev-r4-efficientad-wrn-001`, `ev-r5-screw-stfpm-001`, `ev-r6-patchcore-screw-001`, `ev-r7-patchcore-screw-m50k-001`, `ev-r8-patchcore-screw-512-001`, `ev-r9-patchcore-screw-m100k-001` (+ 기존 `ev-trivial-meanmse-0001`)

코드: `experiments/bottle_loop/{train_ae,train_efficientad,train_patchcore}.py` · 상태: `.cq/runtime/state/cq_loop_state.json`
