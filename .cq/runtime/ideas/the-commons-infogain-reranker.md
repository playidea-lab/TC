# The Commons — Information-Gain Reranker Design Cycle

> role-definition 사이클이 v0.1 rerank를 placeholder로 재규정했다.
> 이 사이클은 그 placeholder를 대체할 reranker의 *목적함수와 posterior
> 표현*을 확정한다. (the-commons-role-definition #다음사이클후보-1)

## 왜 이 사이클인가

[[the-commons-role-definition]]에서 D2(목적함수=정보이득)·D3(v0.1=placeholder)
가 확정됐다. "정보이득"은 그러나 수사였다 — 불확실성을 가진 *확률변수*와
그 *추정 방법*이 비어 있었다. 이 사이클이 그 빈칸을 채운다.

## 결정화한 설계 (Canonical)

> reranker의 목적함수는 **retrieved top-K 이웃에서 "어느 recipe가 이기나"에
> 대한 사후분포의 기대 엔트로피 감소를 최대화**하는 것이다. posterior는
> **recipe별 켤레사전(Beta / Normal-Inverse-Gamma)을 spine으로, 저데이터
> regime에서 LLM이 informed prior를 공급하는 하이브리드(empirical-Bayes)**
> 로 표현한다. posterior는 매 /recommend 요청 시 retrieved evidence에서
> 일회성 fit하고 응답 후 폐기한다 — stateless 정체성과 정합.

## 이번 사이클의 확정 결정

### ID1. stateless는 A(Bayesian)를 막지 않는다 — 제약 과대평가 정정

stateless = 요청 *사이* 무상태. 요청 *안*에서 retrieved top-K로부터
posterior를 fit하고 버리는 것은 허용. ephemeral per-request fit이므로
유지되는 per-cluster posterior 금지 규칙에 저촉되지 않는다. 따라서 A와 C는
동격 대안이 아니라 **A가 목적, C는 A의 싼 그림자**다. (초기 분석에서 내가
stateless 제약을 과대평가해 C를 권장한 것을 정정.)

### ID2. 목적함수 = recipe 사후분포의 기대 엔트로피 감소

확률변수: "이 retrieved 이웃에서 어느 recipe가 이기나(또는 정규화 metric을
가장 높이나)". 다음 실험 추천 = 그 결과가 관측되면 사후 엔트로피를 가장
크게 줄일 것으로 기대되는 후보. 음성·실패 evidence는 별도 페널티 항이
아니라 사후분포의 실패 카운트(Beta β 증분)로 **구조적으로** 1급.

### ID3. posterior 표현 = ① 켤레사전 spine + ② LLM informed prior 하이브리드

- **① recipe별 켤레사전 (Beta / Normal-IG)**: 이웃 내 recipe별 성공/정규화
  metric을 Beta 또는 Normal-IG로 모델, retrieved 카운트로 사후 갱신. info
  gain 닫힌형. 요청별 fit, 싸다 (MCMC 없음). C는 이것의 퇴화형으로 흡수 —
  싼 경로를 잃지 않는다.
- **② LLM-as-prior (저데이터 regime)**: retrieved 이웃에 특정 recipe의 real
  evidence가 희소(0~소수)할 때 ①은 prior 그대로 → 엔트로피 추정 불안정.
  이때 LLM(Gemini)이 world knowledge로 informed prior(α₀·β₀ / Normal-IG
  하이퍼파라미터)를 공급. real evidence 누적 시 likelihood가 prior를 덮어
  ①이 인수.

근거: 사용자 통찰 — "초기 불안정성을 ②가 꽤 크게 잡을 수 있다". ② 단독은
불투명·미보정, ① 단독은 cold-start 불안정 → 결합이 두 약점을 상쇄.

### ID4. 하이브리드 = synthetic-tier auto-retire의 수학적 쌍대

LLM-informed prior는 *posterior 형태의 synthetic seed*다. real Beta 갱신이
그것을 자연히 압도(retire)한다 — 이미 확정된 synthetic-tier + auto-retire
(`retirement_real_threshold`) 기전과 *같은 모양*. 비전이 두 군데서 동일
구조로 닫힌다. 별도 retire 로직을 새로 발명할 필요 없음 — 같은 임계 철학을
posterior 도메인에 사상.

## 요구사항 (EARS)

### 기능

- **RR1** WHEN cq가 /recommend를 호출할 때, reranker는 retrieved top-K로부터
  recipe별 사후분포를 요청 시점에 fit하고, 후보를 *기대 사후 엔트로피 감소*
  순으로 랭킹한다. 요청 간 posterior를 보존하지 않는다.
- **RR2** WHEN 이웃에 특정 recipe의 real evidence가 저데이터 임계 미만일 때,
  LLM이 그 recipe의 informed prior를 공급하고 사후를 그 prior에서 출발시킨다.
- **RR3** WHILE real evidence가 누적될 때, likelihood가 LLM prior를 점진
  지배하여 LLM 기여가 자동 감쇠한다 (별도 retire 트리거 없이 수학적으로).
- **RR4** WHEN 음성·실패 evidence가 retrieved set에 포함될 때, 이를 해당
  recipe 사후의 실패 관측(Beta β 증분 / Normal-IG)으로 반영한다 — 후처리
  페널티가 아니라 likelihood 항으로.
- **RR5** WHERE 응답을 반환할 때, 각 추천에 사후 요약(평균·불확실성)과
  기대 정보이득을 근거로 동봉한다 — TC는 사실·근거 반환, 정책은 호출자.

### 비기능

- **stateless**: posterior fit은 요청 self-contained, 폐기. per-cluster
  상태 유지 금지.
- **저비용**: 켤레사전 닫힌형 — 요청당 sub-second, embedding+LLM prior 호출
  포함 /recommend latency 예산 내.
- **정합성**: LLM-prior 감쇠가 synthetic auto-retire와 같은 임계 철학 공유.

### 범위 외 (다음 사이클)

- **regime 핸드오프 임계**: ②→① 전환 데이터량 경계. synthetic
  `retirement_real_threshold`(현재 3)와 정합 설계 — 별도 사이클.
- 이질 metric → 이웃 내 비교가능 성공/점수 정규화 함수 (A/B/C 공통 선결,
  별도 사이클에서 정밀화)
- LLM-prior 보정·leakage 검증 (prior가 retrieved evidence를 우회 학습?)
- 기대 엔트로피 감소 추정의 평가 프레임 (단일 정답 부재 — proxy 지표)
- v0.1 listwise rerank → 하이브리드 reranker 마이그레이션 운영 계획

## 리스크

| 리스크 | 심각도 | 초기 대응 |
|--------|--------|----------|
| regime 핸드오프 잘못 → LLM이 real 깔아뭉개거나 cold-start 회귀 | 높 | synthetic threshold 기전과 정합, 별도 사이클서 데이터로 튜닝 |
| 이질 metric 정규화 실패 → 사후가 무의미 | 높 | A/B/C 공통 선결 문제로 격리, 정규화 사이클 선행 |
| LLM-prior 미보정/over-confident | 중 | prior를 약하게(넓은 분산) 시작, likelihood가 빨리 이기게 |
| 켤레 가정(Beta/Normal) 부적합 metric | 중 | metric 종류별 켤레족 매핑 표, 안 맞으면 ③ 부트스트랩 fallback |
| 요청별 fit이 latency 예산 초과 | 중 | 닫힌형 유지, K 상한, LLM-prior는 저데이터 recipe에만 호출 |

## 탐구 중 발견한 인사이트

1. **stateless ≠ no-computation** — 요청 안 ephemeral posterior fit은
   stateless와 정합. 제약을 과대평가하면 목적함수를 잘못 약화시킨다.
2. **C는 A의 그림자였다** — 음성 페널티는 사후 실패 카운트의 손흉내.
   목적을 제대로 세우면 싼 경로가 퇴화형으로 공짜로 따라온다.
3. **하이브리드 prior = synthetic seed의 쌍대** — 비전의 핵심 기전이
   posterior 수학에서 다시 같은 모양으로 출현. 새 발명 아님, 사상(mapping).
4. **사용자 반론이 설계를 단단하게 했다** — "stateless라서 C?"가 제약
   과대평가를 드러냈고, "②도 같이"가 cold-start 약점을 메웠다.

## 구현 가정 (이번 빌드 고정 — 사용자 결정)

미결 2개는 별도 사이클을 기다리지 않고, 이번 구현에서 아래 *명시적
잠정값*으로 고정한다 (사용자가 트레이드오프 인지 후 자동 구현 선택 —
가정이 데이터로 틀리면 재작업 수용).

- **이질 metric 정규화 = 이웃 내 min-max** : retrieved top-K 안에서 각
  evidence의 target metric을 [0,1]로 min-max 스케일, intent.direction
  (lower/higher_is_better) 반영해 "성공도"로 변환. 추후 정규화 사이클서
  교체 가능하도록 정규화를 단일 함수로 격리 (Protocol 경계).
- **regime 핸드오프 임계 = synthetic과 동일(3)** : recipe별 이웃 내 real
  evidence < 3이면 LLM-prior 우세, ≥3이면 likelihood 우세. settings의
  `retirement_real_threshold`를 재사용(별도 상수 신설 금지) — ID4 쌍대성
  유지. 추후 정합 사이클서 분리 가능.
- **분포족 = Beta 단일 고정 (Normal-IG 미사용)** : pre-mortem critique 결과,
  posterior 분포족을 태스크별 "택1"로 열어두면 T-IG-002/003/004 간 불일치.
  **min-max 정규화된 [0,1] 성공도를 Beta의 평균으로 보는 Beta(α,β)** 단일
  채택 — 켤레, 미분엔트로피 닫힌형, 음성=낮은 정규화점수→β 가중이 구조적.
  llm_prior는 Beta 하이퍼파라미터(α₀,β₀)만 공급. 모든 태스크 이 가정 공유.

## 다음 사이클 후보

1. **regime 핸드오프 + synthetic threshold 정합 정밀화** (잠정값 검증·분리)
2. **이질 metric 정규화 함수 정밀화** (min-max → 분포기반 등)
3. **기대 엔트로피 감소 평가 프레임** — proxy 지표 (단일 정답 부재)
4. **LLM-prior leakage·보정 검증**

## 관련

- [[the-commons-role-definition]] — D2/D3 (목적함수=정보이득 / v0.1=placeholder)
- [[the-commons-matchmaker-design]] — Hybrid retrieve-and-rerank 원설계
- [[the-commons-vision]] — synthetic-tier + auto-retire (ID4 쌍대 기전)

---

*Generated by /pi on 2026-05-18 — infogain-reranker design cycle: 4 decisions (objective=expected-entropy-reduction / posterior=conjugate-spine+LLM-prior hybrid / stateless-compatible / synthetic-tier dual)*
