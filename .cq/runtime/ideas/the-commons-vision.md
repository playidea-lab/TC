# The Commons — Vision Refinement Cycle

> 📍 **현 정체성 SSOT는 [docs/IDENTITY.md] 다.** 이 문서는 그 정체성에 이른 *역사적 결정 과정*(사이클 기록)이다 — 현재 정의가 아니라 어떻게 거기 왔는지의 기록.

> ⚠️ **거버넌스 정정 (2026-05-19, 사용자 권위):** 이 카드의 거버넌스
> 결정(#3 "분사 약속 약화", #거버넌스 "사유 자산 아님 / evidence는
> contributor 귀속 / CDLA / 사유화·재라이선싱 불가 / 무료 read")은
> **폐기**된다. 확정 모델: TC는 **PI Lab 사유 플랫폼**(팔란티어/HF식).
> 코드만 Apache-2.0 OSS(self-host 가능), 운영 인스턴스·수집 코퍼스는
> **PI Lab 자산**, 기여자는 **귀속+마일리지**(데이터 소유 아님). 위키피디아/
> 모질라식 "공공재·사유 불가" 프레이밍은 중간 과회전이었고 팔란티어
> 결정으로 복원됨. 다른 섹션(stateless/intent/immutability/마일리지 기전)은
> 유효. 상세: memory `project_tc_governance.md`.

> ML 실험 evidence의 매치메이커 + (PI Lab 운영) 도서관. 기여는 마일리지·귀속으로 보상.

## 왜 이 아이디어인가

cq_ml 사이드 세션에서 3-layer 비전(pcq·cq·Commons)이 정리된 직후, 그 비전을
**실제 운영 가능한 결정 집합**으로 정밀화한 사이클. 이번 라운드의 의의는
"비전이 멋있다"에서 "다음 사이클에 무엇을 만들지 결정 가능"으로 옮긴 데 있다.

핵심 통찰 셋:

1. **stateless advisor + cq stateful** — Commons는 도서관·매치메이커 정체성을 유지하고,
   다단계 investigation 사이클의 상태는 cq가 보유한다. 이 분리가 거버넌스/SRP/프라이버시
   세 축을 동시에 단순화한다.
2. **공개 vs 안 보냄의 binary** — fingerprint 단계화는 비전을 흐린다.
   "개인정보 제외 표준 공개" 한 가지 정책 + paid private 모드.
   시스템이 PHI를 *자동 차단*해서 contributor가 매번 고민할 필요 없음.
3. **분사가 아니라 마일리지** — Mozilla식 비영리 분사 대신 Palantir/HuggingFace식
   통합 ecosystem. 기여 → 마일리지 → 활용 권한의 reciprocity 순환으로
   네트워크 효과를 가속.

## 풀고자 하는 문제

ML 연구는 다음 세 가지 문제를 안고 있다:

1. **음성·실패 결과의 휘발** — Papers with Code, OpenReview, 학회 모두 "통과한 것만"
   남는다. "이건 해봤는데 안 되더라"가 사라져서 다음 사람이 같은 실패를 반복.
2. **추천의 부재** — "내 문제와 비슷한 데이터·리소스에서 누가 무엇을 썼나"를
   알려주는 시스템이 없다. AutoML은 단일 머신 내, leaderboard는 SOTA만 본다.
3. **공공재 신뢰 부족** — 기여한 evidence가 *내 것*인지 *플랫폼 운영자 것*인지
   불분명한 SaaS 모델은 학계·정부·민감 도메인이 망설인다.

## 기존 대안과 차이

| 대안 | 1급 자산 | 한계 | Commons 차별점 |
|------|---------|------|---------------|
| Papers with Code | 논문+코드 링크 | evidence가 글로만, raw 없음 | raw run_record 자체가 자산 |
| HuggingFace Hub | 모델·데이터셋 | 실험 *과정* 없음 | 과정·실패·재현 보존 |
| W&B/MLflow | 시각화·실험 추적 | 개인 격리, 공유는 글로 | 공동 코퍼스로 자라남 |
| OpenReview | 논문+리뷰 | 음성결과 휘발 | 음성·실패가 1급 |
| AutoML(autogluon 등) | 단일 머신 최적화 | cross-user 학습 없음 | 코퍼스 기반 매치메이커 |
| MLCommons | 벤치마크 표준 | 정답이 정해진 task만 | 임의 문제·리소스 매칭 |

## 이번 사이클의 확정 결정

### #1 Commons = stateless advisor / cq = 사이클 상태 보유

Commons API는 매 호출 stateless:
`(problem + worker spec + recent evidence hints) → 후보 N개`

다단계 investigation 사이클(EDA → 후보 → 실행 → 평가 → 재추천)의 *상태*는
cq에 살고, Commons는 매 단계마다 새로 질의받는다. Commons는 도서관·매치메이커
정체성 유지, cq는 단순 executor 이상의 investigator engine으로 격상.

이 분리의 이득:
- Commons SRP 유지 — 컨트롤 플레인 책임 없음
- 프라이버시 일관성 — 사용자 데이터에 가까운 사이클 상태가 사용자 측에 머묾
- cq의 가치 추가 — investigator engine이 cq에 추가됨

### #2 pcq run_record에 intent 3필드 추가

```json
"intent": {
  "goal": "baseline_reproduction" | "sota_challenge" | "ablation"
        | "hyperparam_sweep" | "exploration",
  "expected_baseline": { "metric": "mpjpe", "value": 48.0 } | null,
  "tolerance": { "direction": "lower_is_better", "margin": 2.0 } | null
}
```

옵셔널 + null 허용. null intent는 추천 코퍼스에서 weight ↓.
"음성·실패 결과 1급 자산" 약속이 이 필드로 비로소 의미 가짐
(actual > expected + tolerance = 실패의 정의).

pcq 2.x 스펙 변경 사항.

### #3 분사 약속 약화 (premature decision 회피)

README의 "Phase 2 Foundation spin-out (committed)"을
**"거버넌스 진화는 미래 옵션, 시점·형태는 그때의 데이터로 결정"**으로 약화.

day-one 약속은 분사 형식이 아니라 본질:
> Commons는 PI Lab 사유 자산이 아니다. evidence는 contributor 귀속.

운영비 mix도 같이 미룸 (1년 후 cycle).

### #6 공개(default, free) vs private(paid) 2-모드

단계·tier 없음. 단순한 binary:

| 모드 | 의미 |
|------|------|
| public (default, free tier) | 표준 evidence 전체 공개. PHI는 시스템이 자동 차단. |
| private (paid tier) | Commons에 안 보냄. cq 안에서만 실행·기록. |

**"개인정보가 아닌 것"의 시스템 차원 정의**:
- 공개: shape, 통계 모먼트, sample count *대역*, config, metric, intent, manifest, worker spec
- 자동 차단: raw sample/image/text, 환자 ID, 이메일, 정확한 sample count (대역으로 quantize)

contributor는 매번 "어디까지 공개?" 고민 안 함. "기여하느냐 안 하느냐"만 선택.

### #7 3-layer immutability

| Layer | 자산 | 정책 |
|-------|------|------|
| L1 immutable | run_record.json, attribution, content hash | 변경 불가 |
| L2 append-only | lineage 엣지 (derives_from·reproduces 등), validation, comment | 추가만, 삭제·수정 불가 |
| L3 mutable | tag, 도메인 분류, 큐레이션 노트, persona 평판 | 수정 가능, 이력 보존 |

Wikipedia의 *editable*은 ML 맥락에서 *큐레이션 가능*으로 좁혀짐.
evidence 자체는 재현성을 위해 immutable, 그 위에 분류·연결·평판이 자라난다.

PHI 사후 누출 발견 시: L1 evidence는 못 지우지만 L3 *visibility 플래그*로 숨김
(추천 코퍼스에서 제외, 본인만 조회).

### 거버넌스: Palantir/HuggingFace식 통합 ecosystem

분사 없음. PI Lab이 운영자 + 멤버 동시. cq + Commons가 같은 ecosystem.

day-one 약속:
- evidence는 contributor 귀속 (CDLA-Permissive 또는 동등 라이선스)
- Commons read는 누구에게나 무료
- PI Lab은 evidence 사유화·재라이선싱 불가
- 큐레이션·거버넌스 결정은 RFC 형태로 공동체와 협의

미래는 열려있다 — 자라난 후 분산 거버넌스든 재단이든 그때의 데이터로.

### 거버넌스: 마일리지 reciprocity

evidence 기여 → 마일리지 → 활용 권한의 순환.

| 적립 | 점수 |
|------|------|
| evidence 기증 (intent + 표준 공개) | +N (풍부도 비례) |
| evidence 기증 (private 도메인, intent only) | +N/3 |
| lineage 엣지 추가 (L2) | +α |
| 큐레이션 (L3) | +β |
| **내 evidence가 인용됨** (reproduce/derives_from 연결) | +γ (가장 큼) |

| 소비 | 비용 |
|------|------|
| 기본 검색·read | 0 (누구나) |
| 매치메이커 표준 추천 | 0 (contributor·paid 동등) |
| 매치메이커 고급 추천 (다단계·메타 분석) | 마일리지 차감 또는 잔액 |
| API rate limit 상향 | 비례 |
| L3 큐레이션 권한 | 임계값 unlock |

안전장치:
- 마일리지는 **돈으로 못 산다** (anti-Wikipedia 방지)
- 시간 감쇠 — 활성 contributor 우대
- gaming 방지 — validation + duplicate detection + persona 평판 결합
- paid track 차별 없음 — 돈도 운영비 기여로 인정, 다른 경로의 1급 시민

두 트랙 정합:
| 트랙 | 진입 | 활용 권한 | 청중 |
|------|------|---------|------|
| Contributor (free) | evidence 기증 | 마일리지 → 고급 추천 | 일반 ML 연구자·학생 |
| Paid | 구독 | 마일리지 무관, 풀 액세스 | 의료·금융·기업 |

검증된 reference: Stack Overflow reputation, Wikipedia edit privileges, 항공 마일리지.

## 요구사항 (EARS)

### 기능 요구사항

- **R1** WHEN cq가 추천을 요청할 때, Commons는 stateless하게 후보 N개를 반환한다.
  사이클 상태를 보유하지 않는다.
- **R2** WHEN evidence가 ingestion될 때, pcq 2.x 포맷의 intent 필드를 검증하고
  null이면 weight를 낮춰 인덱싱한다.
- **R3** WHEN contributor가 public 모드로 evidence를 보낼 때, 시스템은 raw sample·
  ID·이메일·정확한 sample count를 자동 제거하고 표준 fingerprint로 정규화한다.
- **R4** WHEN evidence가 인용(reproduce·derives_from)될 때, 원 contributor에게
  마일리지 보너스(+γ)가 적립된다.
- **R5** WHEN PHI 누출이 사후 발견될 때, L3 visibility 플래그로 숨김 처리하고
  L1 evidence는 보존한다.
- **R6** WHERE 거버넌스 결정이 필요할 때, RFC 형태로 공개 협의 후 변경 changelog를
  공개한다.

### 비기능 요구사항

- **재현성**: L1 (evidence·attribution·hash) 영구 보존, 변경 불가
- **프라이버시**: PHI 자동 차단을 *시스템 차원*에서 보장. contributor 책임 최소화
- **공정성**: 마일리지는 돈으로 매수 불가. 기여로만 적립
- **자율성**: contributor의 evidence는 contributor 소유. 라이선스로 보증

### 범위 외 (Out of Scope — 다음 사이클)

- pcq 1.x → 2.x 마이그레이션 운영 계획
- 마일리지 인플레이션 정밀 모델 (감쇠 곡선, 환산식)
- ingestion API 구체 설계
- 매치메이커 알고리즘 (어떤 추천 모델·feature 사용)
- 외부/내부 메시징 비유 통일 (ML 소믈리에 / investigator 중 택1)
- 분사 시점·형태 (자라난 후)
- 운영비 mix 비율

## 리스크

| 리스크 | 심각도 | 초기 대응 |
|--------|--------|----------|
| stateless API가 chatty해서 latency ↑ | 중 | cq 측 캐싱 + bulk query 패턴 |
| intent null evidence가 너무 많아 추천 품질 ↓ | 중 | weight 차등 + UI에서 intent 입력 친절 유도 |
| 마일리지 gaming (가짜 evidence farming) | 중 | validation + duplicate detection + persona 결합 |
| PHI 자동 차단의 false negative (놓침) | 높 | 다층 필터 + audit log + opt-out 빠른 응답 |
| 통합 운영이 "PI Lab 자산" 의심 받음 | 중 | CDLA-Permissive 라이선스 day-one 박음 + RFC 거버넌스 |
| pcq 1.x evidence 호환성 | 중 | 마이그레이션 도구 + 1.x evidence는 weight 약간 ↓로 흡수 |
| 마일리지가 contributor 분극화 (top 1% 독점) | 낮 | 시간 감쇠 + 인용 보너스의 *받는 쪽* 가중 |

## 탐구 중 발견한 인사이트

1. **단계 시스템은 비전을 흐린다** — 4단계 → 3단계 → binary로 단순화하면서 발견.
   "공개 vs 안 보냄"이 가장 비전 정신에 충실하고, 시스템 표준화가 강해진다.
2. **"분사"는 형식이고 "사유 자산 아님"이 본질** — Palantir/HuggingFace 모델이
   네트워크 효과·자율성·운영 안정성 셋을 동시에 만족.
3. **마일리지는 새 발명이 아니다** — Stack Overflow·Wikipedia·항공 모두 검증된 패턴.
   Commons에 적용 시 evidence 인용이 가장 큰 적립원이 되어야 *좋은* evidence가 자라남.
4. **stateless vs stateful의 분리가 SRP를 살린다** — cq를 단순 executor로 좁히려던
   초기 비전과 달리, cq에 investigator engine을 *주는* 게 SRP·프라이버시·자율성
   세 축 모두에 이득.
5. **intent 필드 하나가 "음성 결과 1급 자산" 약속의 spec 기반** — intent 없이는
   음성 evidence가 비교 불가능한 잡음. 3필드(goal·expected·tolerance)가 최소·충분.

## 다음 사이클 후보

1. **pcq 2.x 스펙 작성** — intent 3필드 + data fingerprint 표준 + PHI 차단 규칙
2. **ingestion 설계** — public API 형태, 첫 endpoint, validation 파이프라인
3. **마일리지 알고리즘 정밀화** — 적립·소비 가중치, 감쇠 곡선, gaming 방지
4. **CDLA-Permissive 라이선스 적용** — README에 박고 contributor agreement 초안
5. **매치메이커 v0.1** — PI Lab 내부 corpus(cqml/HMR/dental/UTH)로 시드한 첫 추천 엔진
6. **메시징 통일** — ML 소믈리에 vs investigator 중 단일 비유 선택

## 참고 자료

- `/Users/changmin/git/cq_ml/.cq/runtime/ideas/the-commons-vision.md` — 직전 비전 정리 사이클
- `/Users/changmin/git/TheCommons/README.md` — 비전 문서 (이번 사이클로 부분 갱신 예정)
- knowledge insights: ins-bb538121, ins-4a94c6c4, ins-ac4dab52
- reference 패턴: Stack Overflow reputation, Wikipedia + 봇 모델, HuggingFace Hub, Palantir Foundry, MLCommons, Papers with Code, GitHub OSS

## 관련

- [[the-commons-vision]] — cq_ml의 직전 비전 정리
- [[pcq-positioning]] — pcq 정체성 사이클
- [[pcq-spec-foundation]] — spec 분리 사이클

---

*Generated by /pi on 2026-05-13 — vision refinement cycle: 6 decisions crystallized*
