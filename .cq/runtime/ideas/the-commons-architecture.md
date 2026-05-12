# The Commons — Architecture Cycle

> 마이크로서비스로 분리된 CQ + TC, 그러나 TC 자체는 monolith, Phase 1에선 CQ 뒤에 숨김.

## 왜 이 아이디어인가

직전 사이클(`the-commons-vision`)이 *비전 결정*을 정밀화했다면, 이번 사이클은
그 비전을 **운영 가능한 아키텍처**로 옮긴다. "TC는 CQ의 일부인가 별도 서버인가"라는
씨앗 질문에서 출발해, 5가지 아키텍처 root 결정으로 수렴했다.

핵심 통찰 셋:

1. **CQ ↔ TC는 마이크로서비스, TC 자체는 monolith** — 두 layer 사이엔 API 경계,
   TC 내부엔 패키지 경계. 외부 분리는 portability·SRP를 강제하고, 내부 통합은
   첫 출시 부담을 줄인다.
2. **TC는 CQ의 backshelf** — Phase 1에서 외부는 CQ만 본다. TC는 internal service.
   evidence storage, match-maker, library 책임에 집중. UX·결제·인증은 CQ.
3. **진화 경로 명시** — Phase 1 (CQ-only gateway) → Phase 2 (public read API) →
   Phase 3 (public write + 분사 시 identity 분리). 첫해엔 1만, 자라난 후 2/3.

## 풀고자 하는 문제

비전 사이클이 끝난 시점에 남은 문제:

1. **기술 경계가 어디인가** — 비전은 "분리" 정신, 실용은 "통합" 정신. 둘이
   충돌하지 않게 만드는 *물리적 분리 정도*가 정해지지 않으면 첫 줄 코드를 못 쓴다.
2. **누가 어떤 데이터 owner인가** — 마이크로서비스가 의미 있으려면 SSOT가
   엔티티별로 명확해야 한다. 안 그러면 동기화 지옥.
3. **외부에 무엇을 보이는가** — TC public API의 범위가 정해지지 않으면 인증·
   abuse 방어·CDN·indexing 전략을 못 세운다.

## 기존 대안과의 차이 (아키텍처 측면)

| 패턴 | 운영자 | 분리 정도 | 비전 정신 정합도 |
|------|-------|---------|---------------|
| Wikipedia + MediaWiki | Wikimedia Foundation | 코드 분리, 인프라 통합 | ⭐⭐ (분사 모델) |
| HuggingFace Hub | HF Inc. | 마이크로서비스 (같은 인프라) | ⭐⭐⭐ (가장 가까움) |
| GitHub + Actions + Pages | GitHub Inc. | 마이크로서비스 | ⭐⭐ |
| Palantir Foundry + Gotham | Palantir | 모듈러 모놀리스 | ⭐⭐ |
| arXiv (Cornell 단독) | Cornell | 완전 분리 | ⭐ (외부 시스템 의존성 약함) |

→ **HuggingFace 패턴 직역**. 단일 운영자(PI Lab), 마이크로서비스 분리, 같은 인프라,
별도 도메인 (cq.pilab.kr / commons.pilab.kr 같은 분리는 Phase 2부터).

## 이번 사이클의 확정 결정

### #1 CQ ↔ TC = 마이크로서비스 (같은 인프라)

- 별 repo, 별 DB, 별 서버
- 같은 Kubernetes 클러스터·모니터링·로깅
- 통신은 인증 HTTP API (gRPC vs REST는 plan 단계)

**왜**: HF 패턴. 코드/DB 분리 → corpus portability 확보. 인프라 통합 → 운영 효율.

### #2 TC 자체 = monolith (내부 패키지 모듈)

- TC = 단일 서비스, 단일 코드베이스, 단일 DB
- 내부 6개 모듈: library / match-maker / ingestion / lineage / mileage / search-index
- 모듈 경계는 패키지(Go 기준) / namespace로 강제
- 자라난 후 일부 모듈 분리 가능 (search-index가 첫 후보)

**왜**: 첫 출시에 6개 마이크로서비스는 over-engineering. 모놀리스 내 모듈 분리로
SRP 확보 + 추후 분리 옵션 열림.

### #3 Identity owner = CQ

- CQ가 사용자 가입·인증·결제 1차 책임
- TC는 CQ identity를 reference (signed token으로 검증)
- 외부 contributor도 CQ를 통해 identity 획득

**왜**: TC가 CQ 뒤편 backshelf 모델에 부합. 첫 출시 인증 일원화. 단점: 분사 시
identity 분리 비용 — 그러나 #3 결정(분사 약속 약화)으로 부담 완화.

### #4 외부 노출 = Phase별 진화

```
Phase 1 (지금 시작)
─────────────────────────
외부 ─→ CQ (API gateway) ─→ TC (internal)
       가입·인증·결제·UI    storage·match-maker·library

Phase 2 (자라난 후, optional)
─────────────────────────
외부 ─→ CQ ─→ TC
   └────anonymous read API──→ TC

Phase 3 (자라난 후, 분사 검토 시)
─────────────────────────
외부 ─→ TC (자체 identity + write API)
       └─→ CQ는 여러 orchestrator 중 하나
```

**Phase 1에 결정**: TC public API 없음. CQ가 유일한 gateway. anonymous read 불가
(CQ free tier 가입 후 read).

**왜**: 첫 출시 운영 부담 최소. 인증·DDoS·rate limit·CDN 부담 없음. 진화 옵션은
열어둠.

### #5 데이터 ownership 매핑

| 엔티티 | SSOT | 다른 쪽 |
|--------|------|--------|
| identity, persona | **CQ** | TC가 reference |
| paid tier billing, session, auth token | **CQ** | TC가 trust |
| worker spec metadata | **CQ** | TC가 인덱스 복제 (추천용) |
| job, cycle state | **CQ** | — |
| evidence (run_record, manifest, validation) | **TC** | CQ는 transit·임시 buffer |
| lineage edges (L2) | **TC** | — |
| tags, classifications, reputation (L3) | **TC** | — |
| mileage balance | **TC** | CQ가 표시만 |
| recommendation cache | **TC** | CQ가 fetch만 |

**왜**: 마이크로서비스의 SSOT 원칙. CQ는 사용자·요금·실행 책임, TC는 evidence·
matching·library 책임. 겹치면 동기화 지옥.

## 비전 문서 갱신 필요한 부분

기존 README의 "cq is not the only executor" 표현이 Phase 1과 어긋남.
*executor*를 *orchestrator*로 정밀화 필요:

- 코드 실행은 third-party runner OK (local pcq run, CI, 학술 클러스터 등)
- 단 ingestion 경로는 Phase 1에서 CQ가 유일. Phase 2/3에서 직접 ingestion 개방.

## 요구사항 (EARS)

### 기능 요구사항

- **R1** WHEN CQ가 추천을 요청할 때, TC는 stateless HTTP API로 후보 N개를 응답한다.
  TC는 사이클 상태를 보유하지 않는다.
- **R2** WHEN 사용자가 evidence를 기증할 때, CQ가 1차 receiver로 받아 TC에 forward한다.
  TC는 ingestion 단계에서 PHI 자동 차단을 적용한다.
- **R3** WHEN TC가 매치메이커 매칭을 위해 worker spec을 사용할 때, CQ로부터 인덱스
  복제본을 받아 사용한다. SSOT는 CQ.
- **R4** WHEN 외부 사용자가 TC corpus를 read할 때, 첫 출시에서는 CQ free tier 가입을
  통해 접근한다. Phase 2 이후 anonymous read API 개방을 검토한다.
- **R5** WHERE 두 서비스의 인증이 필요한 호출이 발생할 때, CQ가 발행한 signed token으로
  TC가 검증한다 (별도 OAuth provider 불필요).
- **R6** WHILE 두 서비스가 같은 클러스터에서 운영되는 동안, internal traffic은
  mTLS 또는 동등한 인증으로 분리된 namespace 경계를 통과한다.

### 비기능 요구사항

- **portability** — TC 코드·DB·schema가 단독으로 동작 가능해야 한다 (분사 시 이전 비용 ↓).
- **첫 출시 부담 최소** — TC public API·인증 system 없이 시작.
- **운영 통합** — 두 서비스가 같은 클러스터·로깅·모니터링 stack을 공유.
- **데이터 SSOT** — 같은 엔티티가 양쪽 DB에 *마스터*로 존재하지 않는다.

### 범위 외 (Out of Scope — 다음 사이클)

- API protocol 결정 (REST vs gRPC vs GraphQL) — plan 단계
- TC 내부 모듈 간 경계 정밀화 (Go package vs Python module vs Node workspace 등)
- search index 구현 (vector DB 선택, embedding model)
- 인증 token 포맷 (JWT vs PASETO vs 자체 schema)
- Phase 2 public read API 설계 (rate limit, abuse 방어, CDN)
- 분사 시 identity 분리 마이그레이션 계획
- worker spec sync 메커니즘 (push vs pull, refresh frequency)

## 리스크

| 리스크 | 심각도 | 초기 대응 |
|--------|--------|----------|
| Identity가 CQ에 묶여 분사 시 분리 비용 | 중 | 분사 약속 자체가 약화됨(#3 비전). Phase 3 도래 시 별도 마이그레이션 cycle |
| Worker spec 양쪽 DB 분리로 sync 오류 | 중 | CQ가 SSOT, TC는 인덱스 복제 + 변경 이벤트 stream |
| TC monolith가 자라며 단일 장애점 화 | 낮 | 내부 모듈 분리로 추후 일부 service 추출 가능 |
| HTTP API latency가 사이클당 N회 누적 | 중 | CQ 측 캐싱 + bulk query 패턴 + connection pooling |
| Phase 1 외부 read 불가가 "공공재" 정체성 약화 | 중 | "Phase 2 read 개방" 약속을 day-one 비전 문서에 박음 |
| CQ free tier 가입 강제가 외부 학자 진입 마찰 | 낮 | free tier가 진짜 free임을 명시 (이메일만 받음) |
| 두 서비스 인증 signed token 보안 취약점 | 중 | mTLS + token 짧은 TTL + key rotation 정책 |

## 탐구 중 발견한 인사이트

1. **"마이크로서비스 vs 모놀리식"은 binary가 아니다** — 5가지 분기(모놀리식 / 모듈러
   모놀리스 / 마이크로서비스 같은 인프라 / 완전 분리 / 라이브러리)가 존재. 사용자의
   binary 직관을 정밀화해야 sweet spot이 보인다.
2. **CQ ↔ TC 분리와 TC 내부 모듈 분리는 다른 결정** — 외부 경계는 portability 위해
   분리, 내부 모듈은 출시 속도 위해 통합. 두 결정이 동시에 가능.
3. **"readable to anyone without payment" ≠ "anonymous read"** — 무료 가입 read는
   비전과 양립. 비전 문서가 *payment*만 약속했지 *anonymous*는 약속한 적 없음.
4. **executor와 orchestrator의 구분이 비전 문서를 정합하게 만든다** — 코드 실행은
   third-party OK, ingestion 경로는 CQ 단독 (Phase 1). 약속이 약화된 게 아니라
   *정밀화*된 것.
5. **Phase별 진화 경로가 첫 출시 부담을 90% 줄인다** — Phase 1 internal only로
   시작하면 인증·DDoS·CDN·rate limit·abuse 방어 부담이 모두 *지금* 결정 안 해도 됨.

## 다음 사이클 후보

1. **API protocol 결정** — REST vs gRPC. internal microservice엔 gRPC가 일반적이지만
   tooling·디버깅 부담 검토 필요.
2. **TC 내부 모듈 boundary 명세** — 6개 모듈의 책임·인터페이스 정밀화.
3. **인증 token 설계** — CQ가 발행하고 TC가 검증하는 signed token format.
4. **worker spec sync 메커니즘** — CQ → TC 인덱스 복제 (event stream / cron / push).
5. **TC schema 초안** — evidence·lineage·tags·mileage·persona reference 테이블 구조.
6. **pcq 2.x 스펙 작성** — intent 3필드 + data fingerprint 표준 + PHI 차단 규칙.
7. **README "executor → orchestrator" 한 줄 정밀화**.

## 참고 자료

- 직전 사이클: `the-commons-vision.md` (이 디렉토리)
- 비전 문서: `/Users/changmin/git/TheCommons/README.md`
- HuggingFace Hub architecture (참고 패턴)
- Wikipedia + MediaWiki 분리 모델
- Knowledge insights: ins-bb538121, ins-4a94c6c4, ins-ac4dab52, ins-0265526c

## 관련

- [[the-commons-vision]] — 직전 비전 정밀화 사이클
- [[pcq-positioning]] — pcq 정체성
- [[pcq-spec-foundation]] — spec 분리

---

*Generated by /pi on 2026-05-13 — architecture cycle: 5 root decisions crystallized*
