# The Commons — What It Is

> **정체성 SSOT.** TC가 *무엇인가*를 한 곳에 확정한다. 다른 문서와 충돌하면 이 문서가 이긴다.
> 거버넌스(누가 소유·보상)·운영(배포·DB)은 여기 없다 — [링크] 참조. 여기는 *기술적 본질*.

---

## 1. 한 줄 정의

**새 문제(데이터 + 제약)를 profile로 정의하면, 누적지식 위에서 자율 탐구로 솔루션 공간을
illuminate하고, 결과를 영속 누적해 *시간이 지날수록 강해지는* 연구 엔진.**
사람이 문제를 틀 짓고, 기계가 탐구·기억·귀납한다.

---

## 2. 본질 — 이다 / 아니다

| 이다 | 아니다 |
|------|--------|
| 누적학습 자율 탐구 폐루프 | AutoML 마법상자 (X — 사람이 탐색 틀을 준다) |
| 사람-기계 협업 연구 엔진 | 단순 RAG (X — 검색이 아니라 귀납·탐구) |
| 다양성 보존 illumination | 단일 최적 탐색 (X — 트레이드오프 지도를 그린다) |
| 시간↑ → 강해지는 기억 | 완전 자동 (X — 문제 정의는 사람 몫) |

반복 질문("실험계획기지?", "stateless RAG야?", "최적기록 추천이지?")에 대한 답: 셋 다 아니다.
TC는 *문제를 받아 탐구하고 기억하는* 엔진이고, 추천은 그 안의 한 도구다(§5).

---

## 3. 핵심 가설 (검증 중)

정체성은 *주장*이 아니라 *반증 가능한 명제*다. 데이터가 유일한 진실.

> **명제**: TC의 누적지식(corpus + LLM-free 귀납)이 — *시간이 지날수록* —
> ① LLM 상식 ② 세션 휘발 기억 ③ 단발 추천 보다 낫다.

- **검증**: 사전등록 A/B kill-test (`tc_ab_killtest_preregistered`) —
  cold-blind / cold-LLM / warm 3-arm으로 "누적지식 > LLM 상식"을 유명-도메인 편향과 분리해 측정.
- **상태**: 진행 중. 명제가 틀리면 이 정체성을 고친다 — 정체성은 데이터에 종속된다.

---

## 4. 3-주체 맥락 — TC가 어디 서는가

```
pcq (계약)        cq (실행)              TC (도서관·사서·탐구 기반)
evidence 형식      워커·잡·NATS           이 문서의 주제
spec/describe      코드 디스패치·GPU      pcq를 읽고 · cq에 디스패치하고 · 결과를 누적
```

- **pcq** — evidence(run_record)의 형식 계약. TC는 이걸 *읽기만*(vendored spec).
- **cq** — 실행 오케스트레이터(closed-source 바이너리). TC는 cq에 *디스패치*.
- **TC** — pcq evidence를 누적(도서관)하고, 귀납(사서)하고, 탐구를 떠받친다(기반).

TC는 셋 중 하나일 뿐 — 실행도 형식도 cq·pcq의 일. TC는 *기억과 탐구의 층*.

---

## 5. 역할 — 3겹 (핵심)

### ① 도서관 (Library)
- 검증된 evidence를 **불변(L1)** 누적. **음성·실패 결과가 1급** — "안 된 것"이 검색공간을
  좁히므로 성공만큼 가치. 다른 데서 사라지는 증거를 보존한다.
- content-hash 주소화(이식성·재현성의 토대 — 매체가 아니라 바이트가 정체성).
- 코드: `src/the_commons/library/`, `corpus/`.

### ② 사서 (Librarian — 귀납)
- `tc_knowledge`: corpus에서 recipe별 config 축의 metric 추세(increasing/decreasing/
  non_monotonic)를 **순수계산(LLM-free)**으로 귀납. 사실(개별 시도) → 교훈(패턴).
- 실증: LID supervised `epochs↑ → 미검률 0.26→0.08`(ep19 최적, ep23 과적합)을 corpus서 자동 귀납.
- **처방하지 않는다** — "memory↑→auroc↑"까지가 시스템, "그러니 더 키울까/천장이니 딴 거"
  판단은 *맥락 풍부한 에이전트*. 시스템 내부 LLM은 항상 세션 에이전트보다 맥락이 적다.
- 코드: `src/the_commons/knowledge/`.

### ③ 탐구 기반 (Exploration substrate)
- explore-loop QD 컨트롤러(`map_elites`)를 **호스팅**하고 archive를 영속한다.
- **TC가 탐구하는 게 아니다** — 탐구의 *결정론 정책*(다음 셀 추천·placement·exploit/explore)과
  *기억*을 제공한다. **운전자는 에이전트**(Claude Code + `/loop`), 코드 저술·실행도 에이전트.
- dispatcher(Worker 추상)로 로컬·원격 워커에 무관하게 평가를 보낸다.
- 코드: `src/the_commons/exploration/`, `src/the_commons/dispatcher/`.

> **격하 메모**: `tc_recommend`(cross-user 정보이득 매치메이커)는 *별도 역할이 아니라 ②③ 안의
> 한 도구*다. 5h 폐루프 검증에서 추천(LLM이 next_config 합성)은 quota·context-blind로 약했고,
> 폐루프를 실제로 닫은 건 *환류 + 에이전트 판단*이었다. 추천은 콜드스타트 보조로 남는다.

---

## 6. 경계 — 안 하는 것

- **처방 안 함** → 판단은 에이전트. TC는 사실·추세·기억만.
- **데이터 자동 이해 안 함** → 문제의 *틀*(BD축·metric·recipe 후보)은 사람이 profile로 정의.
- **단일 최적 아님** → 다양성 보존 illumination(트레이드오프 지도). 단일 최적이 목표면 hill-climb이 빠르다.
- **recipe 풀 밖 보장 안 함** → 새 방법은 explore_tier2(에이전트 저술)·explosion(웹 SOTA)이 *기회적*으로.
- **탐구의 판단 주체 = 에이전트** → TC는 기반(controller + 기억)이지 결정자가 아니다.

---

## 7. 도메인-무관성

새 데이터·제약은 TC에게 **profile 한 장**이다 — TC 코어는 0 변경.
- profile = 데이터 로더 + 평가(metric·제약) + recipe 후보 + BD축 정의.
- 새 문제를 풀려면: `experiments/<domain>/profile.{py,md}` + recipe 작성 → 같은 엔진이 탐구.
- **증거 — 3 도메인, 같은 엔진**:
  - `mvtec` (공개 이상탐지 벤치마크)
  - `autoresearch` (카파시 nanochat LLM 코드 진화 — 이미지 아님)
  - `lid` (실 산업 결함검사 — 자체 데이터, 미검/과검 제약)
- 셋이 완전히 다른 문제인데 같은 도서관·사서·탐구 기반이 돌았다 = 도메인-무관 입증.

> 단 profile 안의 *판단*(BD축·제약 스칼라화·recipe 선정)은 도메인 지식이 필요 — 사람이 `/pi`로 정한다.
> TC는 그 틀 안에서 자율 탐구·누적·귀납을 한다.

---

## 8. 폐루프

```
   탐색(QD 컨트롤러, 에이전트 운전)
        │
        ▼
   디스패치(cq 워커, MPS/GPU)
        │
        ▼
   도서관 적재(corpus, 불변·영속)  ──┐
        │                            │  fly + Supabase (24/7)
        ▼                            │  시간↑ → corpus↑ → 사서 귀납↑
   사서 귀납(tc_knowledge)  ─────────┘
        │
        ▼
   다음 탐색 (귀납지식이 에이전트 판단을 증폭)
```

탐색이 도서관을 키우고, 도서관이 사서를 똑똑하게 하고, 사서가 다음 탐색을 돕는다 —
영속이라 *세션이 끝나도, 운영자가 바뀌어도* 지식이 산다.

---

## 9. 권위 선언

- **이 문서가 현 정체성의 SSOT다.** 다른 문서(vision·role-definition·architecture·
  success-metrics)와 충돌하면 이 문서가 이긴다.
- 그 문서들은 *역사적 결정 과정*(어떻게 여기 왔나)으로 보존된다 — 폐기 아님, 사이클 기록.
- 정체성이 바뀌는 유일한 조건: §3 핵심 가설이 데이터로 반증될 때.

---

## [부록] 정체성 진화 타임라인

> *현재* 정체성은 위 본문이 전부다. 이 부록은 "어떻게 여기 왔나"의 기록일 뿐.

- **v1 — 매치메이커** (`the-commons-role-definition`): "cross-user 정보이득 추천이 하중점,
  도서관은 기전". 반복 질문에 답하려 추천을 중심에 둠.
- **v2 — 누적지식** (`tc-cumulative-knowledge`): 5h 폐루프가 데이터로 보여줌 — 폐루프를 닫은 건
  추천이 아니라 *환류*. 추천을 격하하고 "사서+분석가(기억+귀납), 처방 없음"으로 재정의.
- **v3 — 누적지식 위의 자율 탐구** (R1 + LID + fly 배포, 2026-05): explore-loop QD 컨트롤러를
  TC로 이주(호스팅), dispatcher·sandbox·corpus 적재 폐루프, fly 영속화. 3 도메인 일반화 입증.
  → 현재 정체성.

---

## [링크] 정체성 밖 — 수명이 다른 것들

정체성(불변 본질)과 아래(가변 정책·운영)는 *분리*한다 — 섞으면 정책이 바뀔 때 이 문서가
정정 배너로 오염된다. 그래서 여기엔 *링크만*.

- **거버넌스** (누가 소유·보상: PI Lab 사유 / 마일리지·귀속) → memory `project_tc_governance`,
  idea `the-commons-vision`(거버넌스 정정 배너 포함).
- **배포·내구성** (fly 토폴로지 / DB / corpus export DR) → idea `the-commons-deployment-corpus-durability`.
- **성공 지표** → idea `the-commons-success-metrics`.
- **계약(pcq)** → `docs/vendor/pcq/SPEC-pcq-2.x.md`.
