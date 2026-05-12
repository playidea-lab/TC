# The Commons — v0.1 Success Metrics Cycle

> v0.1이 *동작했다*는 증거의 정의. 3가지 vision event를 정성적 임계값으로, 3개월 측정 기간.

## 왜 이 아이디어인가

직전 onboarding cycle이 *사용자가 무엇을 경험하는지* narrative를 그렸다. 이번 사이클은
그 narrative가 *실제로 일어났다*는 증거를 무엇으로 측정할지 정한다. 출시 *전*에 정해야
사후 합리화가 아니라 *north star*가 된다.

핵심 통찰 셋:

1. **Adoption vs Vision metric은 다른 차원** — 가입자·evidence 건수는 *얼마나 자랐나*,
   loop closure·retire·promote는 *비전이 동작했나*. v0.1은 *증명* 단계라 vision metric이
   root. Adoption은 v0.2~0.3의 north star.
2. **정성적 1건 임계값 = "시연" 정의** — 5건/10건 같은 양적 임계값은 자의적. *1건이라도*
   시연되면 *시스템이 닫혀서 운영된다*는 정의. 양적 성장은 다음 단계 metric.
3. **3개월 sweet spot** — 1개월은 retire 사이클 미발생, 6개월은 v0.2와 겹쳐 의사결정
   늦음. 3개월이 첫 retire 사이클 1~2회 관찰 + 패턴 형성 가능.

## 풀고자 하는 문제

onboarding cycle이 끝난 시점에 남은 문제:

1. **"출시 = 성공"이 아니다** — v0.1을 배포해도 비전이 동작하는지는 별개 문제.
   north star 없으면 출시 후 *무엇을 봐야 할지* 모름.
2. **사후 합리화 차단** — 측정 metric을 *출시 후* 정하면 자기 옹호로 변질. 출시 *전*에
   못 박아야 정직한 검증.
3. **양적 vs 질적 metric의 함정** — 가입자 100명·evidence 1000건이라도 비전이
   *작동* 안 할 수 있음. 자라난 archive에 그칠 수 있음. 비전 약속이 *동작*하는지가
   본질.

## 이번 사이클의 확정 결정

### #1 3-event vision metric — 정성적 임계값 ≥ 1

```
v0.1 SUCCESS DEFINITION

  Required (모두 ≥ 1):
    ✓ Loop closure event
      ▶ "K1의 evidence ID가 K2 추천의 근거 IDs에 포함된 사례"
      ▶ 검증 비전 약속: 기여 → 매치메이커 학습 → 다음 사용자 가치

    ✓ Synthetic retire event
      ▶ "같은 cluster에 real이 누적되어 deprecated된 synthetic 사례"
      ▶ 검증 비전 약속: synthetic은 seed이지 destination 아님

    ✓ Promote/contradict event
      ▶ "사용자가 synthetic 재현 → real로 promote 또는 contradicts 사례"
      ▶ 검증 비전 약속: 검증으로 자라남 + 음성 결과 1급

  Good-to-have (참고):
    • cluster real-dominance: 최소 1개 cluster real ≥ 50%
    • 월별 evidence 증가 추세 양수
```

각 event는 비전 약속의 *세 축*을 직접 검증:
- **Reciprocity** — 기여가 다음 사용자 가치로 환원
- **Synthetic-as-seed** — 시스템이 retire하도록 설계됨
- **Verification-as-growth** — 사용자 재현이 시스템 진화 동력

### #2 측정 기간 = 3개월

- 출시 직후 ~ +3개월
- 1개월: 빠른 시연 검증 (K1·K2 1건). 단 retire 사이클 발생 불충분.
- 3개월: retire 사이클 1~2회 관찰 + 자연 발생 사례 출현 가능 (외부 사용자 포함)
- 6개월: v0.2 사이클 시작과 겹침. v0.1 정산이 v0.2 north star에 반영되지 않음

### #3 3개월 후 verdict — 3 갈래

| Verdict | 조건 | 다음 단계 |
|---------|------|----------|
| **성공** | 3 event 모두 ≥ 1 | v0.2 진입 (비전·아키텍처 기반 확장: 비전·NLP modality, 외부 시드 파이프라인, mileage 모듈 등) |
| **부분 성공** | 1~2 event ≥ 1 | v0.1 유지 + 미달 metric에 집중 (왜 작동 안 했나 — corpus 부족? UI 부재? 시드 약함?) |
| **실패** | 0 event | 비전 재검토. 구현 문제가 아니라 *비전 가정*이 틀렸을 가능성 우선 검토 |

verdict 메커니즘이 *비전 재검토 가능성*을 day-one에 박는 게 중요 — "비전은 옳고
구현만 실패"라는 자기 옹호 회피.

### #4 Self-staged vs 외부 사례 구분

PI Lab이 K1·K2 역할 self-stage 가능. 시연으로는 충분. 단 *외부 발생 사례*가
훨씬 강한 신호:

- 모든 evidence에 *outreach origin* 라벨 (internal vs external)
- verdict 보고서에 internal/external 분리 집계
- 3 event 중 *외부 발생이 단 1건이라도* 있으면 verdict가 *강화된 성공*으로 격상

## 비전 정합 재점검

| 비전 약속 | metric이 검증하는 방식 |
|-----------|---------------------|
| "기여 → 매치메이커 학습 → 다음 사용자 가치" loop | Loop closure event |
| "synthetic은 seed이지 destination 아님" | Synthetic retire event |
| "음성·실패 결과 1급" | Promote/contradict event 중 *contradicts* 사례가 1급 evidence로 보존 |
| "Wikipedia + 봇 모델" | external origin 라벨이 봇/사람 구분 안 함 — 동등 처리 |
| "stateless advisor" | 매 추천 응답이 evidence IDs와 함께 — loop closure 측정 가능 |
| "Always labeled" | synthetic retire 시 *기존 추천 응답의 라벨이 자동 갱신* (deprecated synthetic 표시) |

## 요구사항 (EARS)

### 기능 요구사항

- **R1** WHEN TC가 추천 응답을 만들 때, 응답에 *근거 evidence IDs*를 기록하고
  나중에 loop closure 측정을 위해 audit log에 보관한다.
- **R2** WHEN K2의 추천 응답에 K1의 evidence ID가 포함될 때, TC는 *loop closure
  event*를 record하고 metric counter를 증가시킨다.
- **R3** WHEN retirement worker가 synthetic을 deprecated로 표시할 때, *retire
  event*를 record하고 timestamp와 trigger한 real evidence IDs를 함께 보관한다.
- **R4** WHEN 사용자가 synthetic의 query를 재현하여 real evidence를 deposit할 때,
  TC는 synthetic.verifier를 채우고 *promote* (일치) 또는 *contradicts* (반박)
  event를 record한다.
- **R5** WHILE 모든 evidence가 deposit될 때, *outreach origin* 라벨 (internal /
  external) 이 필수 메타데이터로 박힌다.
- **R6** WHEN 3개월 측정 기간이 끝날 때, TC는 *verdict 보고서*를 자동 생성한다.
  보고서엔 3 event count(internal/external 분리) + cluster real-dominance +
  월별 추세가 포함된다.

### 비기능 요구사항

- **출시 전 정의 고정** — verdict 정의는 출시 *전*에 README에 박힘. 출시 후
  수정 시 *별도 비전 사이클* 필요.
- **자동 측정** — 3 event는 모두 *시스템이 자동* record. 사람의 *해석*에 의존하지
  않음.
- **투명성** — verdict 보고서는 public 공개 (또는 contributor에게 visibility).
  성공도 실패도 숨기지 않음.
- **재검토 가능성** — verdict가 "실패"면 *비전 재검토*를 default 경로로. 구현
  탓하기 회피.

### 범위 외

- 양적 임계값 (verdict에 정량적 score) — v0.2 north star에서 결정
- adoption metric (가입자, 활성 사용자) — v0.2 north star
- verdict 보고서의 UI/공개 형태 — plan
- 외부 사용자 모집 정량 목표 — 별도 cycle
- v0.1 → v0.2 진입 시점의 *구체* 사이클 정의 — verdict 후 결정

## 리스크

| 리스크 | 심각도 | 초기 대응 |
|--------|--------|----------|
| 3 event 모두 PI Lab self-stage로 채워 *진짜 검증* 안 됨 | 중 | external origin 라벨 + verdict에 internal/external 분리. 외부 사례 1건 이상이면 "강화된 성공" |
| Retire 사이클이 너무 보수적(threshold 높음)으로 3개월 내 미발생 | 중 | v0.1 retire threshold는 *낮게* 설정 (예: real ≥ 3건이면 retire). 3개월 모니터링 |
| Loop closure 정의의 모호함 (어느 정도 evidence 영향이 "있음"인지) | 중 | 추천 응답의 *근거 IDs*에 포함 = closure. 정의 binary로 |
| Promote/contradict event가 사용자 행동에 의존 — 발생 0 가능 | 중 | UI에서 *"이 추천 verify by running"* 명시적 권유. synthetic-dominant 추천에 추가 안내 |
| 출시 후 3 event 0개인데 *비전 재검토* 회피 가능성 | 중 | verdict 메커니즘을 day-one README에 박음. 회피 명시 어려움 |
| 양적 metric 부재로 외부 관찰자가 "성공" 정의 약하게 봄 | 낮 | "v0.1은 증명 단계, v0.2엔 양적 metric 도입" 명시 |

## 탐구 중 발견한 인사이트

1. **양적 임계값은 출시 *후*에야 정밀화 가능** — 출시 전에 5건/10건/100건 같은 숫자를
   정하면 자의적. 정성적 ≥ 1이 *증명*의 정확한 정의.
2. **Verdict의 *실패* 갈래가 시스템 신뢰를 만든다** — 성공 시 다음 단계만 정의하면
   자기 옹호. *실패 시 비전 재검토*를 default로 박으면 *진짜 검증*이 가능.
3. **External origin 라벨이 "self-staged 비판"을 차단** — internal/external 구분이
   *자동 메타데이터*면 외부 관찰자의 의심을 사전 차단.
4. **3 event가 비전의 세 축을 직역** — reciprocity·synthetic-seed·verification-growth가
   동시에 동작하지 않으면 비전이 *부분 동작*. 셋 다 ≥ 1이어야 *통합 동작*.
5. **3개월이 운영 + 측정 + 보고서의 sweet spot** — Phase 1 output을 v0.2 input으로
   피드백 가능. 6개월은 너무 늦음.

## 다음 사이클 후보

1. **외부 사용자 모집 전략** — K1·K2 외부 사례 확보. external origin 라벨이 의미 있으려면
   외부 사용자 1~5명 협업 필요. lead time 큼.
2. **v0.1 출시 일정·milestone** — 3~4개월 marathon을 month·week별 어떻게 쪼개나.
3. **Retire threshold 정밀화** — v0.1 cluster density 정의 (어느 fingerprint·recipe
   범위가 한 cluster인가), real ≥ N 임계값.
4. **Verdict 보고서 형식** — public 공개 형태, contributor에게 어떻게 보여주나.
5. **Plan 단계 인수인계** — schema·API·CLI·LLM 파이프라인 정밀 설계.

## 참고 자료

- 직전 사이클: `the-commons-onboarding.md`
- 비전·아키텍처·v0.1 design 사이클 (this directory)
- 비전 문서: `/Users/changmin/git/TheCommons/README.md`
- Knowledge insights: ins-0265526c, ins-d79f75a6, ins-dac4c2ad, ins-341daecf

## 관련

- [[the-commons-vision]]
- [[the-commons-architecture]]
- [[the-commons-v0.1-design]]
- [[the-commons-onboarding]]

---

*Generated by /pi on 2026-05-13 — success metrics cycle: 4 root decisions (3-event metric + 3-month window + verdict 3-branch + origin label)*
