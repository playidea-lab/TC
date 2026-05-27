# explore-loop × autoresearch — hill-climb를 MAP-Elites로, 플랫폼-무관 자율 QD 연구 엔진의 헤드라인 profile

> 카파시 autoresearch(nanochat 자율연구 루프)의 **hill-climb(keep/reset)를 explore-loop의 MAP-Elites로 교체**해, autoresearch 코드를 한 줄도 안 고치고 **explore-loop 엔진의 두 번째(헤드라인) profile**로 흡수한다. 이식성(비-CUDA)을 요구사항으로 못박되 순서는 쿠다-나노챗 먼저.

## 왜 이 아이디어인가

[[explore-loop-qd-rigor]](v2)는 도메인을 교체 가능한 profile로 분리한 QD 엔진(`map_elites.py` 컨트롤러 + 8키 profile 계약)을 이미 갖췄으나, profile이 `mvtec-ad` 하나뿐이라 "profile만 추가하면 같은 엔진 재사용"이라는 도메인-무관 주장이 미검증이다. autoresearch는 그 **첫 외부 검증 도메인**이면서, 다음 이유로 *헤드라인급*이다:

1. **미점유 영역** — 조사 결과 아무도 autoresearch에 QD/MAP-Elites를 붙이지 않았다. "왜 지금·왜 우리"에 답이 있다.
2. **선행연구가 메커니즘을 검증** — LLMatic(arXiv 2306.01102, "NAS via LLMs and Quality Diversity")이 LLM=변이연산자 + QD=NAS를 이미 입증. 융합은 그 메커니즘을 autoresearch의 **고정-compute 프로토콜 + 측정 phenotype BD**에 적용 — 실현가능성↑, 차별점 또렷.
3. **카파시가 손으로 본 걸 자동화** — 그의 실runs에서 "depth 12 개선이 depth 24로 깨끗하게 전이"(스케일-보편)를 수작업 발견. MAP-Elites의 `num_params` 축 illumination이 이걸 **구조적으로** 표면화한다.
4. **외부 전파력** — 83k★ repo 위에서 "한 봉우리(hill-climb) 대신 compute-최적 지도 전체를 찾는다"는 그림은 설명·자랑하기 쉽다.

## 풀고자 하는 문제

**autoresearch의 hill-climb은 한 봉우리에 갇힌다.** "더 좋아지면 git advance, 나빠지면 git reset"은 단일 trajectory 탐욕 탐색이라 다양성 보존이 없다 — 일시적으로 나쁘지만 천장이 더 높은 급진적 아키텍처가 reset으로 버려진다. README의 "NEVER STOP / try radical changes"는 LLM에게 *수동으로 다양성을 주입하라고 부탁하는 반창고*다. 카파시 본인이 "intentionally bare bones baseline"이라 인정한 부분.

대상 사용자: **자율 ML 연구를 밤새 돌리는 사람**(=본인). CUDA(nanochat)와 CPU/MPS(고전 ML) 양쪽. 고통: 단일 best 한 점만 얻고, "어느 영역(규모·메모리)에서 무엇이 통하는가"라는 *지도*를 못 얻는다.

## 기존 대안과 차이

| 대안 | 한계 | 우리가 다른 점 |
|------|------|--------------|
| autoresearch (원본) | hill-climb → 국소최적·다양성 없음, git 단일 브랜치 | MAP-Elites illumination map(셀별 elite 동시 보존), `archive.json` |
| explore-loop (mvtec만) | profile 1개 → 도메인-무관 미검증, BD가 config-유도 주관 정규화(RE2) | autoresearch는 **측정 phenotype BD**(주관 binning 우회) + 2번째 도메인으로 일반화 입증 |
| LLMatic (LLM+QD NAS) | 일반 NAS, 고정-compute 프로토콜·illumination 강조 없음 | autoresearch testbed + 고정 5분 예산 → compute-최적(Chinchilla) 지도 |
| autoresearch 포크들(macos/mlx/amd) | train.py를 백엔드별로 재작성(도메인 코드 포팅) | 엔진은 플랫폼-중립 유지, 플랫폼은 profile(워커+씨앗코드)에만 핀 |

## 요구사항 (EARS)

> 엔진 요구사항 [[explore-loop-qd-rigor]] **RE1~RE11을 계승**(변경 없음). 아래는 이 융합이 *새로 더하는* 것(AR).

### 기능 요구사항 — 코어 (autoresearch profile)
- **AR1** 시스템은 항상 nanochat을 `profiles/autoresearch-nanochat.md`로 호스팅하며, autoresearch의 `train.py`(씨앗 genotype)·`prepare.py`(고정 evaluator)를 **수정 없이** 사용한다.
- **AR2** WHEN 한 실험이 끝나면 THEN 어댑터는 요약 블록(`val_bpb/num_params_M/peak_vram_mb/mfu_percent/num_steps/total_tokens_M/depth`)을 파싱해 `(fitness, BD 벡터)`로 변환한다. 컨트롤러가 max-전제이므로 fitness는 **`-val_bpb`**(부호 반전)로 전달한다.
- **AR3** (구현서 Option C로 확정) 시스템은 항상 BD 격자축을 **실행 전 config에서 결정론 계산 가능한 2축**으로 둔다 — `(size=num_params × shape=aspect_ratio)`. `num_params`는 `build_model_config`+`num_scaling_params` 미러 공식으로 사전 계산(검증: depth8·ar64 → 50.3M). `tokens/mfu/vram`은 **측정치라 격자축이 아니라** describe.json 진단 메타로 로깅(고정 5분 예산 → 사전 binning 불가, 컨트롤러 `_explore` 커버리지 구동이 사전 bin을 요구). compute-최적(params↔tokens) frontier는 셀 메타에서 사후 플롯. mvtec식 주관 정규화(RE2)는 size축에 불필요(num_params는 객관 계산).
- **AR4** 시스템은 항상 hill-climb(keep/reset)를 컨트롤러 select→place로 대체한다. git advance/reset 대신 셀별 elite를 `archive.json`에 보존한다.
- **AR5** IF 변이 train.py가 5분 예산을 초과하거나 크래시하면 THEN 실패를 evidence로 적재하고 해당 셀 placement를 건너뛴다(RE11 계승).

### 기능 요구사항 — 플랫폼-무관 약속 (결정 D2 = "나")
- **AR6** 시스템은 항상 엔진(dispatcher+컨트롤러)을 플랫폼-중립으로 유지한다 — device/backend는 recipe 코드와 워커 선택에만 존재하고 엔진에 CUDA 가정을 두지 않는다. (코드 리뷰로 확인: `cq_dispatch.py`에 cuda/gpu/device 하드코딩 0.)
- **AR7** WHEN profile을 dispatch하면 THEN 그 profile이 지정한 `worker-id`(예: GPU 워커)로 보낸다. profile마다 BD축·metric·워커를 독립 선언한다.
- **AR8** WHERE CPU 고전-ML profile이 추가되면, BD축은 비-GPU 측정치(`학습시간/모델크기/feature수`)로 선언하고 MFU 같은 GPU 전용 축에 의존하지 않는다.

### 기능 요구사항 — 순서·검증·보편
- **AR9** 시스템의 첫 산출물은 쿠다-나노챗 profile이 end-to-end로 도는 것(작은 격자 illumination map 1장)이다. CPU profile은 *얇은 이식성 증명* 마일스톤이며 연구 스터디가 아니다(스코프 폭발 방지).
- **AR10** (보너스) WHEN `num_params` 축을 따라 ≥2 아키텍처/옵티마이저 계열이 같은 방향으로 bpb를 낮추면 THEN 컨트롤러는 이를 **스케일-보편 가설**로 기록한다(카파시 "depth12→24 전이"를 map gradient로 자동 표면화; RE8 계승).

### 비기능 요구사항
- **재현성**: RE9 계승 — 컨트롤러 결정은 seed·archive·profile에서 재현. 비결정은 에이전트의 cross 저술뿐.
- **비교 범위**: 비교는 *같은 지도(=같은 플랫폼·예산) 안*에서만. 지도 간 비교는 하지 않는다(autoresearch도 "플랫폼 간 비교 불가" 명시).
- **무수정 보존**: seed 파라미터는 어댑터가 **환경변수/config로 주입**(train.py 코드 미변경; R2 해소).
- **배치 (D4)**: 엔진·profile·binding·어댑터 → `cq-ops/skills/explore-loop/`. 도메인 코드(`train.py`·`prepare.py` vendored) → TheCommons `experiments/autoresearch/`. idea.md → `.cq/runtime/ideas/`. (cq-ops 경계 = 코어만, 도메인 코드 불포함 — mvtec 선례 그대로.)

### 범위 외 (Out of Scope)
- **병렬/분산 placement (멀티 GPU)** — R1 스코프 콜에서 ⓐ 선택: 첫 산출물은 **작은 격자(예: 4×4) + 단일 워커 sequential**(v2 범위 준수). 병렬은 v2.x로 명시 연기.
- **autoresearch train.py의 비-CUDA 포팅** — 백엔드별 코드 재작성은 도메인 문제(카파시가 미룸, 포크들이 함). 엔진과 무관 — 우리가 풀지 않는다.
- **CPU profile을 진지한 ML 연구 스터디로 키우기** — 얇은 이식성 증명에 한정(AR9).
- **컨트롤러에 mode=min 네이티브 지원 추가** — 어댑터 부호반전(AR2)으로 충분.

## 리스크

| 리스크 | 심각도 | 초기 대응 |
|--------|--------|----------|
| R1 eval 예산: 단일 GPU 밤새 ~96 eval로 큰 격자 못 채움 (+ "단일워커 sequential" v2 범위와 병렬화 충돌) | 🔴 | **작은 격자(4×4) + 단일워커 sequential**(ⓐ 결정). 병렬은 v2.x |
| R5 어댑터 부담: 콜론출력 파싱 + `@metric=` 변환 + `-val_bpb` 반전 + pcq wrapping을 바깥에서 | 🟠 | /plan에서 어댑터를 독립 단위로 설계·테스트. "무수정"의 대가를 어댑터에 집중 |
| R2 무수정 vs seed 주입(RE6) | 🟠 | 어댑터가 env/config로 seed 주입(코드 미변경). autoresearch는 거의 결정론적이라 k=1 우선 |
| R3 노이즈 성격 차이(GPU 비결정성 + 5분 wall-clock jitter → step수·bpb 미세변동) | 🟡 | "결정론" 가정 금지. RE7 분산인지 placement로 흡수, 경계 셀만 재평가 |
| R6 GPU 워커 부트스트랩(torch cu128·kernels·rustbpe + `prepare.py` 데이터 캐시) | 🟡 | dispatch 전 워커 셋업 단계. /plan P-setup으로 분리 |
| R4 단일-task라 universal 의미 변화(cross-task → 단일지도 내 cross-recipe) | 🟢 | profile에 명시. AR10이 "compute-최적 능선이 계열 횡단하나"로 포착 |

## 탐구 중 발견한 인사이트

- **autoresearch의 size축이 mvtec보다 *깨끗하다*(단 통합서 정밀화됨).** mvtec capacity_bin은 recipe별 구체축(memory_size 등)을 주관 정규화(RE2, 엔진 최대 약점)로 묶지만, autoresearch `num_params`는 아키텍처 config(`depth·aspect_ratio`)에서 **객관 공식으로 사전 계산**된다(cross-recipe 주관 정규화 불요). 단 — 처음 헤드라인으로 내세운 "tokens/mfu 같은 측정 phenotype을 격자축으로"는 **착오였다**: 컨트롤러가 빈 셀을 *겨냥*하려면 실행 전 binning이 필요한데 측정치는 실행 후에야 안다. 그래서 측정치는 진단 메타로 강등하고 격자축은 config-계산 가능 2축(num_params×aspect_ratio)으로 확정(AR3 Option C).
- **고정 compute가 "capacity↑→fitness↑"를 frontier로 바꾼다.** 5분 예산에선 모델이 클수록 step이 줄어 단조롭지 않고 최적점이 존재(Chinchilla). `(params × tokens)` 지도 = compute-최적 능선을 직접 그린 그림 — mvtec 단조 가설보다 풍부·legible.
- **플랫폼-무관은 profile 문제지 엔진 문제가 아니다.** `cq_dispatch.py`에 CUDA 가정 0, device는 recipe 코드+워커에만. mvtec이 이미 MPS/CPU에서 돈 게 증거. → "autoresearch를 포팅"이 아니라 "엔진이 N개 profile 호스팅, 각자 플랫폼에 핀". 이식성 못박는 비용 ≈ 0.
- **컨트롤러는 max-only.** `elite_mean()` 기본 `-inf` + `cohen_d`가 `(challenger-elite)` 부호 → bpb(min)는 어댑터 부호반전으로 무수정 흡수.

## 참고 자료

- 원본: [karpathy/autoresearch](https://github.com/karpathy/autoresearch) (83k★, 2026-03 생성), nanochat 축약 단일 GPU 버전
- 직접 선행: LLMatic — NAS via LLMs and Quality Diversity (arXiv 2306.01102)
- AlphaEvolve 구조(프로그램DB=archive·변이=에이전트·evaluator): arXiv 2506.13131. ARCH-Elites/Monte Carlo Elites: arXiv 2104.08781
- 엔진 idea: [[explore-loop-qd-rigor]] (RE1~RE11 계승), v1 [[cq-tc-agentic-exploration-loop]]
- cq-ops 경계: [[cq-ops-skill-system]] (코어만, 도메인 불포함)
- 기존 자산: `cq-ops/skills/explore-loop/`(엔진+`map_elites.py`+profile 계약), `profiles/mvtec-ad.md`(본보기), `experiments/bottle_loop/train_*.py`(recipe 선례)
- 조사 메모: QD×autoresearch 미점유 확인(검색), 카파시 depth12→24 스케일 전이(officechai/agent-wars 보도)

## 구현 정합 (2026-05-27, plan `gentle-chasing-fern` 실행)

- **"profile만 추가, 엔진 무수정"은 거짓이었다.** `run_explore.py`(실주행 루프)가 mvtec을 하드코딩(`import profile_mvtec_ad`, RECIPE_SCRIPT/monitor/metric/profile 라벨) → **후방호환 엔진 3훅 필수**: ⓐ `run_explore.py` `--profile` 동적 import + 상수 profile 위임, ⓑ `evaluate()` materialize/build_command 훅, ⓒ `cq_dispatch.py` `--code-string`+`--command`. `map_elites.py` 컨트롤러는 무수정(Option C 덕).
- **autoresearch 실행 모델 차이 추가 발견**: train.py가 `from prepare import` 의존 + cu128/kernels 환경 → mvtec식 자체완결 pcq 스크립트와 다름. 해법=profile `build_command`가 `PYTHONPATH=vendored 디렉토리` + cu128 `--with`/`--index-url` 지정(prepare.py shipping 불요). **워커 토폴로지(로컬 GPU vs 원격)에 따라 build_command env가 달라지므로 P-setup서 검증 필요**(잠정값).
- **완료(GPU 불요, 검증됨)**: P-vendor(무수정 vendoring, diff0), P-engine(3훅, mvtec 회귀 15/15 통과), P-adapter+profile(`profile_autoresearch_nanochat.py`+`.md`, `num_params(8,64)=50.3M` 정확, bin_rule 2D 비축퇴, materialize 치환+py_compile, 전체 배선 subprocess-mock 통과), 테스트 `test_profile_autoresearch.py` 8/8.
- **남은 것(사용자/GPU)**: P-setup(cu128 워커 워밍 + `prepare.py` 데이터캐시 + `cq auth`), P-firstrun(첫 격자 실주행 → illumination map), build_command env 실검증.

---
*Generated by /pi on 2026-05-27 — [[explore-loop-qd-rigor]]의 2번째(헤드라인) 도메인 profile. 구현 정합 2026-05-27.*
