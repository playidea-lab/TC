# The Commons — Onboarding Journey Cycle

> v0.1 첫 사용자 e2e 시나리오 narrative. 학생 K1이 가입→추천→실행→기증, 일주일 후 K2가 K1의 evidence 영향을 받는 *full loop의 작은 버전*.

## 왜 이 아이디어인가

직전 v0.1 design cycle이 *무엇을 만드는지*(모듈·청중·시드·매치메이커·범위·synthetic
tier·LLM 활용)를 결정했다. 이번 사이클은 그 위에서 *사용자가 무엇을 경험하는지*를
구체 narrative로 그린다. 추상적 schema·API부터 그리면 over-engineering 위험이
크지만, 시나리오부터 시작하면 *모든 결정이 e2e 검증* 가능.

핵심 통찰 셋:

1. **Full loop의 *작은 버전*이 비전 약속을 한 사이클로 검증한다** — K1의 기여가
   K2 추천에 *측정 가능하게* 영향을 주는 시연이 v0.1 출시 시 가능해야, "Commons는
   살아있는 도서관"이 약속이 아니라 동작.
2. **Commons 라벨은 기증 시점에 등장한다** — 추천 받을 땐 *CQ 기능*, 기증할 땐
   *Commons 가입*으로 인식이 자연스럽게 분리. day-one부터 라벨 강요는 진입
   마찰을 늘림.
3. **Synthetic 비율 라벨은 항상 표시** — README *Always labeled* 약속의 직역.
   "12 real + 87 synthetic in this cluster" 같은 라벨이 모든 추천 응답 상단에.
   숨기지 않는 게 신뢰의 출발.

## Narrative — Full Loop (Small)

### Phase 1 — K1이 처음 만나는 흐름

```
[Day 0]
1. K (Kaggle churn 데이터셋 입문 대학원생) — 친구 추천으로 cq 가입.
   웹에서 `cq` free tier 가입 (이메일만).
   `uv add cq` 후 `cq login`.

[Day 1]
2. K가 프로젝트 폴더에서:
     $ cq init
   → cq.yaml 생성. K가 data 경로(./data/churn.csv), target column 명시.

3. K가:
     $ cq recommend
   → CQ가 로컬에서 data profile 계산 → CQ → TC 쿼리.

4. K의 화면에:

     ┌─ Recommendations (5 candidates) ──────────────────────────────┐
     │  ⚠ corpus context: 12 real + 87 synthetic in this cluster      │
     │                                                                 │
     │  1. LightGBM      AUC 0.84 ± 0.03   ~3 min   evidence: ev-...  │
     │  2. XGBoost       AUC 0.83 ± 0.02   ~5 min   evidence: ev-...  │
     │  3. TabPFN        AUC 0.87 ± 0.05   ~1 min   evidence: ev-...  │
     │     (synthetic-dominant — verify by running)                    │
     │  4. sklearn RF    AUC 0.78          ~2 min   evidence: ev-...  │
     │  5. LR baseline   AUC 0.71          ~1 min   evidence: ev-...  │
     └─────────────────────────────────────────────────────────────────┘

5. K가 선택:
     $ cq run 1     # LightGBM
   → CQ가 K의 노트북에서 학습 실행. evidence 자동 생성 (config + metric +
     intent + fingerprint + worker spec).

[Day 1 — 학습 끝난 후]
6. K의 화면에 (Commons 라벨 처음 등장):

     ┌─ Result ──────────────────────────────────────────────────────┐
     │  LightGBM completed. AUC = 0.847.                              │
     │                                                                 │
     │  Your evidence is being deposited into The Commons.             │
     │  (free tier default. opt out with `cq config set private`)      │
     │                                                                 │
     │  ✓ evidence ev-a1b2c3 added to library                         │
     │  ↳ this completes a (problem, recipe) cluster previously        │
     │    seeded with synthetic — your run promoted 2 synthetic        │
     │    records and contradicted 1.                                  │
     └─────────────────────────────────────────────────────────────────┘
```

### Phase 2 — K2가 K1의 evidence를 받는 흐름

```
[Day 7]
7. K2 (다른 학교, 비슷한 churn 데이터셋) — 같은 절차로 가입.

8. K2가:
     $ cq recommend
   → CQ → TC 쿼리.

9. K2의 화면에:

     ┌─ Recommendations (5 candidates) ──────────────────────────────┐
     │  ⚠ corpus context: 14 real + 85 synthetic in this cluster      │
     │                                                                 │
     │  1. LightGBM      AUC 0.845 ± 0.02  ~3 min   evidence: ev-...  │
     │     ↳ 2 real runs (incl. ev-a1b2c3 from anonymous contributor) │
     │  ...                                                            │
     └─────────────────────────────────────────────────────────────────┘
```

K1이 기여한 evidence가 K2 추천에 *측정 가능하게* 영향. 비전 약속 검증 완료.

## 3 미시 결정 (확정)

### #1 Commons 라벨 노출 시점 = 기증 시점

추천 받을 땐 CQ 어휘만. 기증 시점에 "The Commons"라는 이름이 처음 등장. K가
자연스럽게 "내 evidence가 공동 도서관에 들어간다"고 인식.

대안 (처음부터 노출 / 노출 없음) 모두 약점:
- 처음부터: Commons 정체성 강조 ↑ but 진입 마찰 ↑
- 노출 없음: Commons 정체성 사라짐 (비전 약속 약화)

### #2 자동 기증 + 첫 1회 명시 안내

free tier default = 자동 기증 (비전 결정과 정합 — "contribute with credit").
단 첫 evidence 직전 1회 명시: "free tier는 자동 기증입니다. opt-out: `cq config
set private`". 이후 자동.

매번 명시 동의는 마찰 큼. 안내 없는 완전 자동은 사용자가 "내가 모르게 기여" 느낌
가능.

### #3 추천 응답에 synthetic 비율 항상 표시

"corpus context: N real + M synthetic in this cluster" 라벨이 *모든 추천
응답*의 상단에. README *Always labeled* 약속 직역. synthetic-dominant 추천엔
추가 경고 ("verify by running").

## 비전 정합 재점검

| 비전 약속 | narrative 반영 |
|-----------|---------------|
| "Contribution is the membership" | K1이 첫 evidence 기증 시 Commons "가입"으로 인식 |
| "free tier default: contribute with credit" | 자동 기증 + 1회 안내 + opt-out 명령 |
| "Always labeled" (synthetic tier) | "N real + M synthetic" 라벨 모든 추천 응답에 |
| #1 stateless advisor | CQ가 매 `cq recommend`마다 TC에 새 쿼리. stateless |
| #2 intent 3필드 | `cq init`에서 K가 intent를 cq.yaml에 명시 (또는 exploration default) |
| "근거 evidence IDs 첨부" | 각 후보 옆에 evidence ID 표시, 클릭하면 run_record 조회 |
| Synthetic auto-retire | K의 real evidence가 cluster 진입 시 "promoted/contradicted N개" 메시지로 시연 |
| L1 immutable | 기증된 evidence는 evidence ID로 영구 추적. retire는 weight 0이지 삭제 X |
| Wikipedia + 봇 persona attribution | K1의 evidence가 K2에게 *anonymous contributor*로 표시. persona attribution은 v0.2 mileage와 함께 |

## 도출되는 후속 결정들

이 narrative에서 *자동 도출되는* 구체 요구사항 — plan 단계의 출발점:

### schema (TC)

- evidence 테이블: tier flag(real/synthetic), 모든 v0.1 design 결정 필드
- cluster definition: (problem_fingerprint_bucket, recipe_id) 쌍의 density 측정용
- retirement log: 어떤 synthetic이 언제 어떤 real에 의해 retire됐는지

### CQ ↔ TC API (최소 3 endpoint)

- `POST /ingest` — evidence 1건 deposit (real or synthetic flag 포함)
- `POST /recommend` — query(spec + fingerprint + intent) → top-N + corpus context
- `GET /evidence/{id}` — evidence 단건 read

### CQ CLI 명령 (최소)

- `cq init` — 프로젝트 폴더 설정
- `cq recommend` — TC에 query, 후보 표시
- `cq run N` — 후보 N번 실행 + evidence 자동 deposit
- `cq config set private` — opt-out

### UI/메시지 templates

- 추천 응답 box (corpus context 라벨 + 후보 5 + evidence IDs)
- 첫 evidence 기증 직전 안내 message
- 학습 결과 box (evidence ID + cluster 진입 메시지)
- synthetic-dominant 추천 경고

### LLM synthetic 생성 파이프라인 (Day 0 전 작업)

- "tabular churn classification" 같은 problem cluster 정의
- LLM에게 cluster별 synthetic evidence 100~1000건 생성
- attribution 박기 (source_model, prompt_hash, timestamp)
- TC ingestion으로 tier=synthetic deposit

## 요구사항 (EARS)

### 기능 요구사항

- **R1** WHEN K가 `cq recommend`를 실행할 때, CQ는 로컬에서 data fingerprint를
  계산하고 TC에 query 후 top-5 candidate를 응답한다.
- **R2** WHEN TC가 추천 응답을 만들 때, 상단에 "N real + M synthetic" 라벨과
  각 candidate에 근거 evidence IDs를 첨부한다.
- **R3** WHEN candidate가 synthetic-dominant일 때 (해당 cluster에서 synthetic이
  real보다 많음), 추천 응답에 "synthetic-dominant — verify by running" 경고를
  추가한다.
- **R4** WHEN K가 처음으로 `cq run`을 실행하기 직전, CQ는 1회 명시 안내
  ("free tier 자동 기증. opt-out 명령")를 표시하고 confirm을 받는다.
- **R5** WHEN K가 free tier로 학습을 완료할 때, evidence는 자동 deposit되고
  결과 화면에 "Commons에 evidence 추가" 메시지와 cluster 영향(promote/contradict
  count)이 표시된다.
- **R6** WHEN K2가 K1의 query와 유사한 query를 실행할 때, K1의 evidence가
  K2 추천의 근거 IDs에 *anonymous contributor*로 포함되어 표시된다.
- **R7** WHILE K가 `cq config set private`로 opt-out한 동안, CQ는 evidence를
  TC에 전송하지 않고 로컬에만 저장한다.

### 비기능 요구사항

- **첫 사용 마찰 최소화** — 가입~첫 추천까지 5분 이내
- **transparency** — 모든 추천에 *근거 정보 가시*. 숨김 없음.
- **자연스러운 라벨 등장** — Commons 라벨이 처음 등장하는 순간이 *기여하는 순간*
- **재현 가능성** — 추천 받은 N건 candidate는 모두 K가 *재현 시도 가능*
  (synthetic은 LLM 재호출, real은 원본 run_record 조회)

### 범위 외 (Out of Scope)

- 가입 플로우 정밀화 (이메일 verification, password reset 등) — plan
- UI 화면의 정확한 디자인 — plan
- `cq init` 의 cq.yaml schema — pcq 2.x cycle
- intent 입력 UX (자동 추론 vs K가 명시) — 작은 분기, plan
- mileage 표시 — v0.2
- persona attribution 형태 — v0.2 with mileage
- multi-modality (비전·NLP) — v0.2~0.3
- public read API의 화면 — Phase 2

## 리스크

| 리스크 | 심각도 | 초기 대응 |
|--------|--------|----------|
| 첫 1회 안내가 충분히 명시적이지 않아 K가 의도 모르고 기여 | 중 | 1회 안내에 *큰 박스 + opt-out 명령 굵게*. CLI에 `--accept-public` 명시 옵션도 |
| K2의 시연이 *너무 작은 변화*라 차이가 안 보임 (12 → 14 real) | 중 | 시연 환경에선 cluster density 작게 시드하여 K1 한 건의 영향이 visible |
| synthetic-dominant 추천을 K가 *맹신*해서 실행하지 않고 결과 사용 | 중 | 추천 응답에 "verify by running" 경고 + UI에 *추천 confidence*를 시각적 강조 |
| 첫 시연에 PI Lab 사람이 K1·K2 역할 모두 — 외부엔 self-staged 처럼 보임 | 중 | 외부 첫 사용자 1~2명 협업해서 *진짜 K1·K2* 확보 (학회 또는 커뮤니티 접촉) |
| K가 추천 5개 중 *가장 빠른* 옵션(LR baseline 1 min)만 선택 | 낮 | 첫 추천 응답에 "exploration recommended" 같은 *왜 다양한 선택지* 안내 |
| cq.yaml 작성이 처음 사용자에게 진입 마찰 | 낮 | `cq init`이 *대화형*으로 cq.yaml 자동 생성. data 경로만 묻고 나머지 default |
| Commons 라벨이 기증 시점에 처음 등장 → "왜 미리 안 알렸지" 불만 | 낮 | cq 가입 페이지에 *한 줄 footer* — "evidence는 The Commons에 기여됩니다 (free tier default)" |

## 탐구 중 발견한 인사이트

1. **Narrative-first 설계가 추상화 폭주를 막는다** — schema·API부터 그리려 했으면
   필드 30개·endpoint 8개 도출됐을 텐데, 시나리오부터 그리니 필드 핵심·endpoint 3개로
   수렴.
2. **Commons 라벨 등장 시점이 비전 약속의 *경계*다** — 너무 일찍 = 진입 마찰,
   너무 늦게 = 정체성 약화. *기여 직전*이 정확한 sweet spot.
3. **Synthetic 라벨이 README의 약속을 *동작*으로 변환** — "Always labeled"가 한 줄
   약속이 아니라 *모든 추천 응답의 첫 줄*에 있어야 비전이 동작.
4. **K2 시연이 일주일 cycle 안에 가능해야 한다** — full loop의 "작은" 의미는 *완성
   N=2 사용자*가 v0.1 출시 직후 일주일 안에 동작해야 한다는 것. cluster density
   임계값을 v0.1엔 *낮게* 설정해야 가능.
5. **synthetic의 promote/contradicts 메시지가 시스템 *생명력*을 보여준다** — K의
   화면에 "promoted 2 synthetic, contradicted 1"이 보이면 K는 *내가 시스템에
   영향을 미친다*고 즉시 느낀다. 비전의 reciprocity가 mileage 없이도 인식됨.

## 다음 사이클 후보 (plan 단계 진입)

1. **TC schema 초안** — narrative에서 도출된 필드·테이블 정확한 정의
2. **CQ ↔ TC API 정의** — 3 endpoints의 정확한 인터페이스
3. **CQ CLI 명령 명세** — `cq init`/`recommend`/`run`/`config` 정확한 인자·동작
4. **pcq 2.x 스펙 작성** — synthetic flag, attribution, intent, fingerprint
5. **LLM synthetic 생성 파이프라인** — Day 0 전 준비 작업
6. **첫 시나리오 e2e 테스트 작성** — narrative를 자동 테스트 케이스로
7. **첫 외부 사용자 모집 계획** — K1·K2 역할 협업자 확보

## 참고 자료

- 직전 사이클: `the-commons-v0.1-design.md`
- 비전 사이클: `the-commons-vision.md`
- 아키텍처 사이클: `the-commons-architecture.md`
- 비전 문서: `/Users/changmin/git/TheCommons/README.md`
- Knowledge insights: ins-0265526c (vision), ins-d79f75a6 (architecture), ins-dac4c2ad (v0.1 design)

## 관련

- [[the-commons-vision]] — 비전 6 결정
- [[the-commons-architecture]] — 아키텍처 5 결정
- [[the-commons-v0.1-design]] — v0.1 설계 7 결정

---

*Generated by /pi on 2026-05-13 — onboarding journey cycle: full-loop narrative + 3 micro decisions crystallized*
