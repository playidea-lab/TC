# The Commons — v0.1 Design Cycle

> TC 첫 출시(v0.1)의 모듈·청중·코퍼스·알고리즘·범위를 결정. tabular vertical slice + LLM-distilled synthetic evidence tier로 cold start 해결.

## 왜 이 아이디어인가

직전 architecture cycle이 *외부 경계*(마이크로서비스, monolith, identity, Phase별 노출)를
정했다. 이번 사이클은 그 monolith의 *내부*를 본다 — v0.1에 어떤 모듈을 만들고,
누가 첫 사용자이며, 코퍼스는 어디서 오고, 매치메이커는 어떻게 작동하며, 출시 scope는
어디서 끊는가.

핵심 통찰 셋:

1. **단일 ranker, 두 행동** — (b) NN, (c) embedding, (d) learned ranker를 별 알고리즘으로
   보던 분리가 실제로는 환상. 학습된 ranker(예: LightGBM-rank)는 데이터 부족 시 *얕은 트리·
   feature distance 의존*으로 사실상 NN 동작. 코퍼스가 자라며 *학습된 정교한 ranking*으로
   자연 진화. 한 시스템이 데이터 양에 적응.
2. **Synthetic tier가 cold start의 진짜 해결** — 외부 시드 변환 파이프라인(OpenML/HF/Kaggle)이
   v0.1의 critical path였는데, LLM 증류 합성 evidence를 *별도 tier*로 도입하면 1~2개월
   단축. attribution + 감쇠 + auto-retire 정책으로 비전과 양립.
3. **Vertical slice의 학회 1개 vs 다양성 50%** — 1 modality(tabular) 끝-to-끝 완성이
   3 modality 50% 완성보다 *증명 가능*. 자랑할 수 있는 사례 하나가 마케팅·외부 contributor
   유입의 첫 관문.

## 풀고자 하는 문제

architecture cycle이 끝난 시점에 남은 문제:

1. **TC가 *무엇을 가지고 출시되는가*** — 6개 모듈을 다 만들면 1년 걸리고, 어느 시나리오도
   실용 수준 못 됨. 어디까지 v0.1, 어디부터 v0.2인지가 정해지지 않으면 plan 작성 불가.
2. **첫 사용자 가치 명제** — "Commons에 가입하면 무엇이 보이는가"가 한 시나리오로 그려져야
   ingestion·library·match-maker의 *최소 책임*이 도출됨.
3. **Cold start 해결** — 외부 시드 변환은 시간 큼, PI Lab 내부 corpus만으론 부족. 매치메이커가
   *추천할 게 있어야* 가치 있음.

## 이번 사이클의 확정 결정

### #1 v0.1 모듈 = ingestion + library + match-maker (basic)

6개 모듈 후보 (ingestion, library, lineage, search-index, match-maker, mileage) 중
첫 출시 3개. 매치메이커를 *기술적으로* 첫 출시부터 반영해 비전 정체성("도서관 +
매치메이커")이 약속이 아닌 *동작*으로 검증됨. lineage·search-index·mileage는 corpus가
자라며 가치 폭발하는 모듈이라 v0.2~0.3으로 미룸.

### #2 첫 청중 = tabular ML 학생·실무자 (A)

| 후보 | 검증된 강점 |
|------|------------|
| A. tabular ML | seed 풍부(UCI/Kaggle/OpenML), 청중 넓음, AutoML 가설 명확 |
| B. 비전 baseline | PyTorch Hub·timm 비교군 강함 — differentiation 약함 |
| C. PI Lab 내부 only | corpus 다양성 부족 — 외부 generalize 어려움 |
| D. AutoML 호환 | 알고리즘 부담 너무 큼 — v0.2~0.3 후보 |

PI Lab 내부 비전·의료 corpus는 **다양성 보강용**으로 병행. 외부 광고는 tabular,
내부 검증은 비전·의료. brand 균형.

### #3 매치메이커 = 단일 learned ranker, 데이터 양에 자연 적응

```
단일 ranker (e.g., LightGBM lambdarank)
  Input pair: (query_features, candidate_features)
  Output:     relevance score → top-N 추천

  corpus dense  → 깊은 트리, 학습된 정교한 ranking
  corpus sparse → 얕은 트리, feature distance 의존 (NN 동작)

  cold start (query 주변 evidence < N건):
    → 휴리스틱 fallback ("tabular+binary+N<1000 → TabPFN/LightGBM small")
    → 응답에 "근거 부족(휴리스틱)" 신뢰도 라벨

  응답: top-N candidate, 각각:
    • recipe identifier
    • expected metric range (corpus 통계)
    • 근거 evidence IDs (3~5건, 사용자가 추적 가능)
    • confidence label
```

#### 입력 features

| query 측 | candidate(recipe) 측 |
|----------|---------------------|
| worker spec (CPU/GPU/RAM) | recipe identifier (LightGBM, ResNet50 등) |
| data fingerprint (shape, modality, dtype, count band, 모먼트) | recipe metadata (hyperparam 범위, framework) |
| intent (goal/expected/tolerance) | corpus 관찰 metric 통계 (mean/std/percentile) |

#### 학습 objective

- pairwise ranking loss (lambdarank 류)
- 음성/실패 run이 *학습 데이터*에 직접 포함 → 비전 약속 "null/negative 1급"이
  ranker 학습에 반영됨

#### 업데이트 정책

- 매일/매주 batch retrain (online learning은 불안정)
- 신규 evidence는 retrain 전이라도 NN-fallback 경로로 즉시 활용

### #4 시드 = PI Lab 내부 + LLM-distilled synthetic evidence

외부 시드(OpenML/HF/Kaggle)는 v0.1에서 *시급도 낮음*. 대신:

- **PI Lab 내부 corpus** — HMR/dental/UTH/cqml 등 실제 run record. Real tier, full weight.
- **LLM 증류 합성 evidence** — codex/gemini/claude로 tabular 1만~10만 건 합성 record 생성.
  Synthetic tier, reduced weight, attribution 강제, auto-retire 정책 적용.

함의: 외부 시드 변환 파이프라인이 v0.1 critical path에서 빠짐 → 출시 일정 1~2개월
단축.

### #5 v0.1 출시 scope = Vertical slice (tabular only)

```
v0.1 INCLUDED:
  ✓ ingestion: tabular pcq evidence 수신, PHI 자동 차단, validation
  ✓ library: real tier + synthetic tier (격리, immutable, retire 정책)
  ✓ match-maker: tabular 한정 LightGBM-rank + 휴리스틱 fallback
  ✓ seed: PI Lab 내부 + LLM synthetic 1만~10만 건
  ✓ CQ ↔ TC API: ingest / recommend / read evidence (3 endpoints 시작)
  ✓ Retirement worker: cluster density 모니터링, synthetic auto-deprecate
  ✓ UI 라벨: "synthetic"·"근거 부족" 명시

v0.2 DEFERRED:
  ✗ 비전(image)·NLP modality
  ✗ 외부 시드 (OpenML/HF/Kaggle) 변환 파이프라인
  ✗ lineage(L2) 모듈
  ✗ search-index 정밀화 (vector + keyword)
  ✗ mileage(reciprocity) 모듈
  ✗ public read API (Phase 2)
```

### #6 Synthetic evidence tier — bootstrap, retirement, attribution

```
EVIDENCE STORE
├── Real tier   ← PI Lab 내부 + (v0.2부터) 외부 변환 시드
│   - weight 1.0
│   - permanent
│   - 비전 약속(raw, immutable, reproducible) 전부 적용
│
└── Synthetic tier  ← LLM 증류 (codex/gemini/claude)
    - weight 0.3 (예시, 튜닝 대상)
    - 명시 attribution (model, prompt_hash, timestamp)
    - "synthetic" 라벨 UI 항상 표시
    - auto-retire 정책:
        same (problem-cluster, recipe)에 real N건 누적 시
        → synthetic 해당 records *deprecated* 플래그 + weight 0
        → 학습·추천 corpus에서 제외 (audit엔 남음)
    - 사용자 재현 시:
        → 결과 real evidence로 등록
        → synthetic.verifier 필드에 real_evidence_id 채워짐
        → "promote(일치)" 또는 "contradicts(반박)" 둘 다 비전과 정합
```

핵심: synthetic은 *seed*이지 *destination*이 아니다. 시스템이 retire하도록 설계됨.

### #7 LLM 활용 4트랙 (synthetic + 3개 보조)

1. **Synthetic evidence 생성** (위 #6)
2. **Recipe pool 자동 작성** — "tabular classification recipe 100개" → LLM 초안 → PI Lab 검증·승인 → catalog commit
3. **Cold start heuristic 작성** — "tabular ML cold start rules" → LLM 초안 → PI Lab tuning
4. **추천 응답 설명 텍스트** (옵션) — 매치메이커 응답에 "왜 이 recipe가 적합한가" 자연어 설명 (정합성은 evidence ID로 검증 보장)

## 비전 정합 재점검

| 비전 약속 | v0.1 반영 |
|-----------|----------|
| #1 stateless advisor | ranker stateless. 매 query 처음부터 score. |
| #2 intent 3필드 | query feature에 들어가 의도별 차등 추천 |
| "null/negative 1급" | 실패 evidence가 ranker 학습 데이터에 직접 |
| "공개/private binary + PHI 자동 차단" | private은 corpus 진입 안 함. ingestion에서 PHI 차단 |
| #7 L1 immutable | real·synthetic 둘 다 immutable. retire는 weight=0이지 삭제 아님 |
| "마일리지 — 인용 보너스" | v0.1엔 mileage 모듈 없으나 응답의 *근거 evidence IDs*가 인용 데이터 흐름 준비 |
| "Wikipedia + 봇" | LLM이 *봇 contributor*. attribution 강제로 transparency 보장 |
| "Reciprocity" | v0.2부터 mileage 모듈 추가 시 활성 |

## 요구사항 (EARS)

### 기능 요구사항

- **R1** WHEN ingestion이 evidence를 받을 때, real/synthetic tier flag를 검증하고
  tier별로 분리 저장한다.
- **R2** WHEN synthetic evidence를 deposit할 때, attribution(source_model, prompt_hash,
  generated_at)이 필수 필드로 강제된다.
- **R3** WHEN 같은 (problem-cluster, recipe)에 real evidence가 N건(임계값) 누적될 때,
  retirement worker가 해당 클러스터의 synthetic records를 *deprecated*로 표시한다.
- **R4** WHEN 매치메이커가 학습할 때, real(weight 1.0) + active synthetic(weight 0.3)을
  사용하고 deprecated synthetic은 제외한다.
- **R5** WHEN 사용자가 추천을 요청할 때, 응답에 *근거 evidence IDs*를 첨부하고
  synthetic이 섞여있으면 "real N건 + synthetic M건 기반" 명시한다.
- **R6** WHEN 사용자가 synthetic evidence의 query를 재현하여 real evidence를 deposit할 때,
  TC는 synthetic.verifier 필드를 채우고 "promote(일치)" 또는 "contradicts(반박)" 관계를
  기록한다.
- **R7** WHILE corpus가 sparse한 query가 들어올 때, 매치메이커는 휴리스틱 fallback으로
  응답하고 신뢰도 라벨에 "근거 부족(휴리스틱)"을 표시한다.

### 비기능 요구사항

- **출시 시기**: vertical slice 3~4개월 목표 (외부 시드 파이프라인 빠지면서 1~2개월 단축)
- **interpretability**: 모든 추천이 근거 evidence ID 또는 휴리스틱 출처로 추적 가능
- **transparency**: synthetic은 항상 라벨 표시. 사용자가 *합성 vs 실제* 구분 즉시 가능
- **자동 진화**: real evidence 누적에 따라 매치메이커가 자동으로 *real-dominant* 추천으로
  이동. 운영자 개입 없음

### 범위 외 (Out of Scope — 다음 사이클)

- 구체 알고리즘 선택 (LightGBM vs XGBoost vs CatBoost rank, lambdarank vs pointwise) — plan
- feature engineering 정밀화 (어떤 통계 모먼트 사용?)
- recipe pool 정확한 형태 (스키마, 100~500개 list)
- 휴리스틱 규칙 정확한 형태
- retrain 주기·trigger 조건
- synthetic weight·retire threshold 정확한 수치
- LLM 호출 비용 모델 (codex vs gemini vs claude — 무엇으로 몇 건)
- v0.2 우선순위 (비전 modality vs 외부 시드 파이프라인 vs lineage 모듈)

## 리스크

| 리스크 | 심각도 | 초기 대응 |
|--------|--------|----------|
| LLM hallucination이 synthetic evidence에 그대로 들어감 | 중 | weight 감쇠 + retire 정책. 사용자 재현이 자정 메커니즘 |
| Recipe pool 검증 부담 — LLM 초안에 PI Lab 사람이 매번 review | 중 | tabular 영역만 우선 100~500개로 제한. modality 확장 시 추가 |
| 휴리스틱 fallback이 hard-code처럼 인식 | 낮 | 응답에 "휴리스틱 추천" 명시 + 자라며 NN으로 교체됨을 UI에서 보여줌 |
| 매치메이커가 데이터 작아서 학습 안 됨 | 낮 | LightGBM-rank는 1k 샘플로도 작동. synthetic 1만건 + real 100건이면 충분 |
| Tabular vertical만으론 PI Lab 비전·의료 brand 약화 | 중 | 내부 corpus(비전·의료) 다양성 보강. "비전 modality는 v0.2" 공식 약속 |
| Retirement 정책의 threshold가 너무 보수적이면 synthetic이 영영 안 사라짐 | 중 | threshold 운영 모니터링 + Phase 1 종료 시 retire 비율 검증 |
| synthetic tier의 read 노출이 외부 신뢰 약화 ("합성 데이터 도서관") | 낮 | day-one README에 *seed, not destination* 정신 명시 |
| LLM 호출 비용 폭증 (수만 호출) | 낮 | 1회성 부트스트랩. cost cap 설정. 자라며 LLM 호출 빈도 ↓ |

## 탐구 중 발견한 인사이트

1. **(b)(c)(d) 알고리즘 분리는 환상** — LightGBM-rank 한 모델이 데이터 양에 따라 *NN 모양 →
   embedding 모양 → learned ranker 모양*으로 자연 적응. 단계 옮기는 부채 없음.
2. **외부 시드 파이프라인이 v0.1 critical path였다** — 사용자 직관("LLM이 수천만 가지를
   경험했으니 외부 변환 없어도 충분")이 이걸 정확히 짚음. synthetic tier 도입 시 critical
   path가 *LLM 비용·검증*으로 옮겨감 (훨씬 가벼움).
3. **"Raw evidence 1급"의 *raw* 정의가 binary가 아니다** — 좁게는 "실제 run", 넓게는
   "표준 schema + 명시 attribution". 후자로 해석하면 synthetic도 *별도 tier*로 양립 가능.
4. **Retirement가 immutability와 양립** — synthetic을 *삭제*하는 게 아니라 *weight 0*으로
   처리하면 L1 immutable 약속 유지 + 매치메이커 corpus 정화 동시 달성.
5. **"검증되며 사라지는" 매커니즘이 reciprocity의 자연 사이클** — 사용자가 재현하면
   synthetic이 real로 promote 또는 contradicts로 반박. 둘 다 corpus 가치 ↑. 일종의
   *자정* 시스템.
6. **Vertical slice가 학회 1개를 만든다** — Horizontal scope은 어느 시나리오도 자랑할 수
   없음. 1 modality 완성된 사례 하나가 외부 contributor 유입의 첫 관문.

## 다음 사이클 후보 (plan 단계)

1. **TC schema 초안** — real/synthetic tier 분리된 evidence 테이블, recipe catalog,
   heuristic rules, retirement audit log
2. **CQ ↔ TC API 정의** — 3 endpoints (ingest, recommend, read by ID) 인터페이스
3. **pcq 2.x 스펙 작성** — synthetic flag + attribution 필드, intent 3필드,
   fingerprint 표준, PHI 차단 규칙
4. **Recipe pool 생성 파이프라인** — LLM 호출 → PI Lab 검증 → catalog commit 워크플로우
5. **Synthetic evidence 생성 파이프라인** — LLM 호출 → schema 변환 → tier flag 박기 →
   ingestion
6. **Retirement worker 설계** — cluster density 측정 알고리즘, threshold 결정, 운영 모니터링
7. **첫 시나리오 e2e 테스트 계획** — tabular 학생 K의 끝-to-끝 흐름을 자동 테스트로 작성

## 참고 자료

- 직전 사이클: `the-commons-architecture.md` (this directory)
- 비전 사이클: `the-commons-vision.md` (this directory)
- 비전 문서: `/Users/changmin/git/TheCommons/README.md`
- Knowledge insights: ins-bb538121, ins-4a94c6c4, ins-ac4dab52, ins-0265526c, ins-d79f75a6
- LightGBM lambdarank 패턴 (참고)
- Wikipedia AI-generated article policy (synthetic tier 정책 참고)

## 관련

- [[the-commons-vision]] — 비전 6가지 결정
- [[the-commons-architecture]] — 외부 아키텍처 5가지 결정
- [[pcq-positioning]] — pcq 정체성
- [[pcq-spec-foundation]] — spec 분리

---

*Generated by /pi on 2026-05-13 — v0.1 design cycle: 7 root decisions crystallized*
