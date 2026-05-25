# cq–TC Autonomous Experiment Loop

> cq가 폐루프 주체, TheCommons는 도서관·소믈리에로서 passive 응답. ε-novelty mix 정책으로 corpus를 자율적으로 두껍게 만들어가는, "사람이 들여다볼 때쯤 풍부한 사전실험"이 쌓여 있는 그림.

## 왜 이 아이디어인가

지금까지 cq/pcq/tc 세 컴포넌트는 한 사이클(추천→실험→ingest)을 닫는 데까지는 갔지만 — 시뮬레이션 사이클 폐쇄 완료(memory: cq_pcq_tc_oneshot_state) — 그 사이클이 **반복적으로 자율 회전**하는 단계로는 아직 못 갔다. 사용자의 비전은 단발 사이클이 아니라 **무한 폐루프**: 추천을 받고 실행하면서 결과를 보고, 다시 추천받고 실행하며, 사람이 들여다볼 때쯤엔 풍부한 사전실험들이 쌓여 있는 형태.

cq는 원래 "대화를 실험으로 바꿔서 실행시키는" 능동 주체이고, PCQ는 실험을 검증 가능한 계약(content_hash + integrity)으로 규격화하며, TheCommons는 (도서관 = L1 immutable corpus + lineage) + (소믈리에 = `/recommend` 엔드포인트)로 정의된다. 이 분담을 그대로 살려 폐루프를 닫는 게 본 아이디어.

## 풀고자 하는 문제

**누가**: 자신의 시간 단위가 분/시간이 아니라 일/주인 연구자. 노트북을 켜둘 수는 있지만 매 사이클을 지켜볼 수는 없다.

**무엇**: 한 사람이 "한 번 직접 돌릴 수 있는 실험"의 총량은 제한된다. 실험은 다음 실험을 정하는 의사결정 비용이 학습 자체보다 큰 경우가 많고, 그 의사결정의 대부분은 "비슷한 과거 실험을 보고 그 옆에 한 칸 시도"하는 식의 routine search. 이 routine search를 자동화하면 사람의 시간은 high-level steer와 결과 해석에만 쓸 수 있게 된다.

**고통**: 직전 PoC(`scripts/cq_pcq_tc_oneshot.py`)는 시뮬레이션으로 사이클 폐쇄를 증명했지만 (a) 자동 반복이 없고 (b) `/recommend`가 retrieve만 하지 "다음 config 추천"을 안 하고 (c) cq 워커가 막혀 진짜 학습 디스패치가 안 되는 상태.

## 기존 대안과 차이

| 대안 | 한계 | 우리가 다른 점 |
|---|---|---|
| Bayesian Optimization (GP/TPE) | recipe·intent 혼재 corpus에서 단일 GP 모델링이 무겁고, intent별 분리 필요 | corpus의 의미(recipe + intent + lineage)를 닫힌형 Beta(infogain) + LLM 합성으로 다룸 — corpus 자체를 모델로 안 만듦 |
| MAB (Thompson/UCB) | 이산 arm 가정. 연속 hyperparam 표현 한계 | recipe-level은 Beta(infogain), within-recipe는 LLM 합성으로 연속/이산 모두 자연 |
| 휴리스틱 sweep ("best ± k") | 단순하지만 corpus가 커져도 학습 안 됨 | infogain이 corpus 구조를 적극 반영, ε wild card가 우물 탈출 보장 |
| 사람이 직접 매 round 결정 | 시간 비용 ↑, routine 결정에 능력 낭비 | passive 운영 + 가끔 intent steer로 사람 시간을 high-level에만 |

## 요구사항 (EARS)

### 기능 요구사항

**E1 사이클 시작 (이벤트)** — WHEN cq가 한 round를 시작하면, cq는 TC `/recommend`에 `query = {intent, worker_spec, data_fingerprint}`를 보낸다.

**E2 분기 결정 — 결정성 (이벤트)** — WHEN `/recommend`가 요청을 받으면, 시스템은 `seed = hash(corpus_size, round_id, intent)` RNG로 ε=0.1 동전을 던져 exploit / explore 분기를 선택한다.

**E3 cold-start 우회 (상태)** — WHILE corpus가 sparse(`is_corpus_too_sparse`)이면, 시스템은 ε-novelty mix를 건너뛰고 `cold_start_candidates`를 `confidence=weak_heuristic`으로 반환한다.

**E4 exploit 분기 (이벤트)** — WHEN exploit이 선택되면, 시스템은 retrieve → infogain rerank → top recipe + 그 recipe의 evidence들 → LLM 합성으로 **within-recipe next_config**를 반환한다.

**E5 explore 분기 (이벤트)** — WHEN explore가 선택되면, 시스템은 corpus 요약 + intent → LLM 합성으로 **corpus 밖 novelty recipe + config**를 반환한다.

**E6 응답 스키마** — `/recommend` 응답의 각 candidate는 `next_config`, `recipe_id`, `policy = {branch, epsilon, version}`를 포함한다.

**E7 학습 실행 (이벤트)** — WHEN cq가 `next_config`를 받으면, cq는 학습을 실행하고 stdout `@key=value` 라인을 메트릭으로 수집한다.

**E8 envelope 빌드 (이벤트)** — WHEN 학습이 완료(성공/실패 무관)되면, cq는 PCQ envelope을 빌드하되 `attribution.policy = {branch, epsilon, version, wild_card_fired}`를 포함한다.

**E9 lineage 분기 마킹 (이벤트)** — WHEN envelope을 ingest할 때, exploit 분기는 `lineage.type="derives_from"`(직전 evidence와 연결), explore 분기는 `lineage.type="exploration"`(best_so_far와 연결, 분기점 마커)로 표기한다.

**E10 영속 상태 (상태)** — WHILE 폐루프가 도는 동안 cq는 `{current_intent, last_round, last_evidence_id, best_metric}`을 영속 저장소에 기록해 재시작 시 이어받는다.

**E11 intent steering (이벤트)** — WHEN 사람이 steer를 발행하면, cq는 다음 round부터 `query.intent`에 갱신값을 반영한다.

**E12 주기 알림 (이벤트)** — WHEN `round_count % N == 0`이면, cq는 `{best evidence, recent k round summary}`를 알림 채널에 보낸다.

**E13 실패 학습 (조건)** — IF 학습 process가 실패하면, THEN 시스템은 실패 자체를 envelope(metrics에 실패 마커)로 ingest한다 — corpus가 "어떤 config가 실패했나"를 학습한다.

**E14 정책 사후 분석 (특성)** — WHERE v1→v2 정책 진화가 필요하면, `envelope.attribution.policy.version` 마커가 사후 정책 비교를 가능하게 한다.

**E15 운영 시간 — 무제한 (상태)** — WHILE 폐루프가 도는 동안, round 수에 하드 제한은 두지 않고 주기 알림(E12)이 사람의 모니터링 hook이 된다.

### 비기능 요구사항

- **결정성**: 같은 `(corpus_state, round_id, intent)`에서 `/recommend`는 같은 분기/next_config를 반환해야 한다 (E2 seed로 보장).
- **재현성**: 학습 entry script는 PCQ `code.content_sha256` + `seeds` + `data_ref`로 재현 가능해야 한다 (기존 PCQ 2.x 계약 유지).
- **stateless 정합**: `/recommend` 호출 사이에 서버 측 상태(Beta posterior 캐시 등) 없음. 매 요청 일회성 fit·폐기. 기존 infogain 정합 유지.
- **비용 가드**: 한 round당 LLM 합성 호출 1회로 제한 (k=1 sequential).
- **가용성**: TheCommons가 재시작돼도 cq 측 영속 상태(E10)로 다음 round 이어받기.

### 범위 외 (Out of Scope)

- **v2 정책 자체 (corpus-decay, stagnation-based)** — v1 운영 데이터로 결정. v1 코드엔 `ExplorationPolicy` 추상화만 두고 구현체는 `FixedEpsilonPolicy` 1개.
- **분산 다중 워커 큐 매니징** — k=1 sequential이라 단일 워커로 충분. cq의 multi-worker는 별 트랙.
- **자동 saturation 종료** — 무제한 + 알림 정책.
- **사람의 veto/pin/모드전환** — passive + intent steer만. 더 강한 제어는 다음 사이클.
- **노트북 외 호스트** — cq worker host 분리(GPU 풀 등)는 cq 측 인프라 문제. 본 아이디어는 cq의 어떤 host에서든 동일하게 동작.

## 리스크

| 리스크 | 심각도 | 초기 대응 |
|---|---|---|
| LLM 합성 결과가 schema 위반(잘못된 hyperparam 타입 등) | 중 | JSON schema 강제 + temperature 0 + 실패 시 cold_start fallback |
| LLM 추천 비용 누적 | 중 | k=1로 비용 cap. 주기 알림에 round당 비용 포함해 사람이 모니터링 |
| wild card가 너무 미친 recipe 제안 (학습이 안 도는 모델 등) | 낮 | 실패도 evidence(E13). 다음 사이클 infogain이 자연 down-rank |
| 폐루프가 같은 영역만 반복 (corpus 한쪽으로 쏠림) | 중 | ε=0.1 wild card 안전판. 정체 신호가 데이터로 보이면 v2 |
| `/recommend` 응답 스키마 변경 → 기존 클라이언트 호환성 | 낮 | `next_config`는 optional 추가. 기존 evidence_ids/expected_metric 필드 유지 |
| infogain Beta가 wild card recipe(N=1)를 너무 적극 우선화 | 낮 | 기대 동작 — wild card → 다음 사이클 자연 흡수. 의도된 흐름 |
| cq 워커 인프라 자체 장애 (현재 막힘) | 높 | 본 아이디어는 cq 측 인프라와 독립. cq worker는 풀리는 대로 적용. 임시로 노트북 셸 wrapper로 흉내 가능 |

## 탐구 중 발견한 인사이트

- **"ε-greedy"라는 이름은 부정확** — 우리 v1은 표준 ε-greedy(MAB)가 아니라 **"ε-novelty mix over infogain"**: 1-ε 분기는 infogain rerank의 expected info gain 기반(=평평한 recipe 우선)이고, ε 분기는 LLM-guided novelty(uniform random 아님). 두 분기 모두 어떤 형태로든 informed.
- **두 층 직렬 분업이 자연** — infogain = recipe-level exploration(어떤 recipe를), LLM = within-recipe exploitation(그 recipe 안 어떤 config). 기존 infogain의 닫힌형 Beta 수학은 그대로 보존.
- **wild card는 다음 사이클 자동 흡수** — N=1 새 recipe는 다음 사이클 infogain에서 Beta 평평 → expected info gain 큼 → exploitation 분기가 자연 그 recipe 안 탐색. "wild card가 우물 밖에서 한 번 던지면 corpus가 흡수해 다음 사이클부터 within-recipe로 굴린다"는 깔끔한 동역학.
- **k=1이 "기본 단위", sweep은 정책 진화의 결과** — 처음부터 batch 모드 박지 않음. corpus가 두꺼워지면 LLM이 자연스럽게 "이 round는 같은 prior에서 k=3"이라 답하는 형태로 진화.
- **lineage가 트리 구조로 자연 풍부** — 초반(exploration) 일렬 chain → 중반(exploitation) 분기 → 후반(local sweep) fan-out. 사람이 들여다볼 때 trace를 그래프로 그대로 읽을 수 있는 자료.
- **policy 메타데이터가 v1→v2 결심을 데이터로 정당화** — envelope.attribution.policy에 (branch, eps, version, wild_card_fired) 박아두면 v1 운영 데이터가 자동으로 의사결정 재료가 됨.

## 참고 자료

- 기존 knowledge: `the-commons-infogain-reranker.md` (켤레사전 Beta spine + LLM prior 설계)
- 기존 knowledge: `the-commons-matchmaker-design.md`
- 기존 knowledge: `the-commons-lineage-and-hash-fix.md`
- 코드 베이스: `src/the_commons/matchmaker/{retriever,composer,service}.py`, `matchmaker/infogain/{posterior,reranker,llm_prior}.py`, `api/recommend.py`
- 기존 시뮬 PoC: `scripts/cq_pcq_tc_oneshot.py` (사이클 폐쇄 증명)
- 메모리: `cq_pcq_tc_oneshot_state.md` (직전 PoC 상태)

---
*Generated by /pi on 2026-05-22*
