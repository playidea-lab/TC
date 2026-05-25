# Agentic Exploration Loop — 강제 탐색 skill (AlphaEvolve-lite / Quality-Diversity)

> LLM-free TC가 잃어버린 탐색 능력을 **에이전트 층의 재사용 skill**로 복원한다. ε-greedy로 매 라운드 "기존 심화 / 안 해본 방법 / 아예 새 방법 창조"를 골라, recipe×category 아카이브(MAP-Elites식)를 발산적으로 채운다. 보편은 게이트가 아니라 아카이브에서 기회적으로 줍는 보너스. TC=프로그램DB, 에이전트=변이연산자, cq=evaluator인 AlphaEvolve-lite 컨트롤러.

> 확장/이주 대상: [[cq-tc-autonomous-experiment-loop]](ε-novelty mix) + [[cq-tc-agentic-novelty-websearch]](정체 트리거·웹검색). 두 idea가 TC matchmaker 층에 설계했던 탐색을, LLM-free 재설계가 삭제(commit d3c47bc·e3013cb)한 뒤 **에이전트 층으로 이주**시키는 것.

## 왜 이 아이디어인가

방금 MVTec 일반화 실험(18라운드·6카테고리)이 **전부 mvtec-patchcore 단일 recipe**로만 돌았다. 원인 분석:
- LLM-free TC(`tc_knowledge`)는 **순수 귀납** = exploit 전용. 추세(사실)만 주고 처방·recipe 제안을 안 한다(KR6).
- 탐색 능력은 본래 TC matchmaker의 ε-novelty mix + LLM/agentic novelty synthesizer에 있었으나, LLM-free 정화가 그 LLM 엔진을 삭제.
- 그 결과 "데이터가 유일한 진실" 귀납이 **corpus support(PatchCore)를 벗어날 내적 동기가 없음** = 전형적 explore/exploit 편향(필터 버블).

이론적 뒷받침: **Novelty Search**(Lehman/Stanley)는 objective만 좇으면 "기만적 국소최적"에 빠짐을 증명 — 우리 PatchCore lock-in이 그 사례. **Quality-Diversity(MAP-Elites)**는 단일 best가 아니라 "셀별 best 아카이브를 발산 탐색으로 채워" 이를 해소. **AlphaEvolve/ShinkaEvolve/LLaMEA**(2025–26)는 "LLM이 루프에서 코드/방법을 변이·진화"하는 정식 패밀리.

지금 시점 의미: 우리는 이미 AlphaEvolve의 3/4(프로그램DB=TC, 변이=에이전트, evaluator=cq)를 가졌고, **빠진 건 컨트롤러(이 skill)뿐**.

## 풀고자 하는 문제

**누가**: TC 폐루프를 운영하는 연구자. "더 넓은 수색"을 원하지만, 에이전트에게 탐색 mandate를 매번 손으로 주입해야 한다(이번 실험은 인계계획이 recipe 고정·exploit-lock이었음).

**무엇**: 폐루프가 seed된 단일 recipe에 갇힌다. 새 방법(efficientad/AE/PaDiM/FastFlow + 커스텀)을 *강제로* 시도하고, 메커니즘 무관한 보편이 있는지 보려면, 탐색 정책이 코드화된 재사용 skill이 필요하다.

**고통**: 매 실험마다 "이번엔 다른 recipe도 해" "정체됐으니 새 거 찾아봐"를 사람이 일일이 지시. routine 탐색 결정에 사람 시간 낭비. 단일 recipe corpus는 "PatchCore 선택 자체가 틀렸을 수도"를 영원히 못 말함.

## 기존 대안과 차이

| 대안 | 한계 | 우리가 다른 점 |
|------|------|--------------|
| AlphaEvolve(폐쇄) | Gemini 결합·분산 evaluator·closed source | TC=DB·agent=변이·cq=eval로 이미 절반 보유, lite 컨트롤러만 추가 |
| OpenEvolve/ShinkaEvolve(오픈클론) | 자체 program DB+LLM앙상블(API키)+evaluator → 우리 것과 중복, LLM-free 위배 | 프레임워크 미도입, 아이디어 2개만 차용(아카이브-프롬프트·cascade) |
| TC matchmaker ε-novelty(삭제됨) | LLM-free 정화로 엔진 제거, recipe corpus 안에서만 재조합 | 에이전트가 외부 가설원(자기 지식+웹) — corpus 밖 novelty 가능 |
| 순수 objective sweep(auroc 최대화) | Novelty Search가 증명한 "기만적 국소최적" = lock-in | QD 아카이브 + 정체 트리거로 발산 보장 |
| 사람이 매 라운드 recipe 결정 | 시간비용·routine 낭비 | ε-greedy 정책 코드화, 사람은 steer만 |

## 요구사항 (EARS)

### 기능 요구사항 — 정책 코어

- **E1 라운드 분기 (이벤트, 결정성)** — WHEN 한 라운드가 시작되면, skill은 `seed=hash(archive_state, round_id, intent)` RNG로 ε 동전을 던져 **exploit(1-ε)** / **explore(ε)** 분기를 선택한다. ε는 기본 0.3, 설정 가능.
- **E2 exploit 분기 (이벤트)** — WHEN exploit이면, skill은 아카이브에서 유망 셀(recipe×category)을 골라 그 recipe의 **within-recipe config를 심화**(예: memory 50k→100k)한다. 방향은 `tc_knowledge`의 해당 recipe 추세를 참조.
- **E3 explore 분기 — 싼 것부터 사다리 (이벤트)** — WHEN explore이면, skill은 **안 해본 recipe**를 비용 오름차순으로 선택한다: ① 미실행 기존-스크립트 recipe(patchcore/efficientad/ae) → ② 소진 시 에이전트가 **새 recipe train.py 저술**(PaDiM/FastFlow/PatchSVDD/커스텀) → ③ 에이전트 지식 소진 시 **웹검색 SOTA**(최후).
- **E4 정체 → 에스컬레이트 (상태)** — WHILE 한 recipe(또는 셀)의 best_metric이 R(기본 5)라운드 정체이면, skill은 다음 explore의 티어를 한 단계 강제 상승(①→②→③)시킨다. (LLaMEA stagnation, [[cq-tc-agentic-novelty-websearch]] E3)
- **E5 중복 거부 (이벤트)** — WHEN 후보 config가 corpus의 기존 시도와 (recipe, 주요 hyperparam) 거의 동일하면, skill은 그 후보를 기각하고 재추출한다. 판정은 `tc_recent_attempts` 조회로. (ShinkaEvolve novelty rejection)
- **E6 콜드스타트 (상태)** — WHILE 대상 category의 corpus가 비었으면, skill은 첫 라운드를 기존-스크립트 baseline(patchcore m50k@384)으로 시작한다(싼 기준점).

### 기능 요구사항 — AlphaEvolve 차용

- **E7 아카이브-프롬프트 변이 (이벤트)** — WHEN 에이전트가 새 recipe를 저술/변형(E3-②③)하면, skill은 **과거 best 프로그램 + 점수를 컨텍스트로 제공**한다(`tc_get_evidence`로 코드, `tc_knowledge`로 추세). "잘 됐던 것에서 영감." (AlphaEvolve Prompt Sampler)
- **E8 cascade 평가 (특성, 선택)** — WHERE 비용 절감이 필요하면, 신규 recipe를 짧은 epoch/작은 config로 먼저 스크리닝 → 유망한 것만 풀 config 디스패치.

### 기능 요구사항 — 아카이브·보편(QD)

- **E9 아카이브 갱신 (이벤트)** — WHEN 한 라운드가 완료되면, skill은 `archive[(recipe_family, category)]`에 best 결과를 기록한다(MAP-Elites 셀). evidence는 `tc_ingest_pcq`로 적재, lineage는 exploit→`derives_from`, explore→`exploration` 마킹.
- **E10 추상축 매핑 — 에이전트 (이벤트)** — WHEN 새 recipe가 들어오면, 에이전트가 그 config 축을 **추상 범주**(capacity/resolution/train_amount/…)에 매핑한다. 안 맞으면 **새 추상 범주를 신설**(taxonomy 확장 가능). TC는 구체 축만 유지(LLM-free).
- **E11 보편 기회적 탐지 (이벤트, 보너스)** — WHEN 한 추상 범주가 **≥2개 recipe에서 같은 방향 추세**를 보이면, skill은 이를 **cross-recipe 보편 후보**로 기록·알림한다. 게이트가 아니라 보너스.
- **E12 출처 보존 (이벤트)** — WHEN 웹검색 기반 recipe가 적재되면, 참조 출처(URL/논문)를 attribution에 보존한다. ([[cq-tc-agentic-novelty-websearch]] E5)

### 기능 요구사항 — 운영

- **E13 영속 상태 (상태)** — WHILE 루프가 도는 동안 skill은 `{archive, round, last_evidence_id, best_per_cell, stagnation_counters, ε, seed}`를 state 파일에 기록해 재시작 시 이어받는다(재진입 가능).
- **E14 종료 (조건)** — IF cross-recipe 보편이 탐지되면 THEN "성공 종료"; ELSE IF 노력예산 D(총 라운드/시도 상한) 소진 시 "no-universal-yet 종료". D는 격자완성이 아니라 시도 횟수.
- **E15 주기 알림·steer (이벤트)** — WHEN `round % N == 0`이면 {아카이브 요약, best-per-cell, 보편 후보}를 알림; 사람은 intent steer(예: "특정 recipe 집중", "웹검색 켜기")로 방향만 조정.
- **E16 실패도 학습 (조건)** — IF 디스패치/학습이 실패하면 THEN 실패를 evidence로 적재(다음 변이의 self-correct 재료). (기존 폐루프 E13)

### 비기능 요구사항

- **LLM-free 정합**: TC는 구체 추세만(귀납). 탐색·추상매핑·novelty는 전부 에이전트 층. TC에 LLM 재주입 없음.
- **비용**: 웹검색(③)은 ε∧티어소진∧정체 때만 발동 → 자연 cap. 추가로 "run당 웹검색 최대 회수" 상한 + caffeinate/예산으로 외부 제어.
- **결정성**: 같은 (archive_state, round, intent)에서 분기·seed 재현 가능. evidence는 PCQ 봉인 유지. 웹검색 비결정성은 attribution.sources로 추적.
- **재사용성**: 임의 데이터셋/recipe군에 재진입 가능한 skill. 상태는 state 파일 1개.
- **안전**: 새 recipe 저술 시 c4_claim 규약·검증(py_compile) 준수. 파괴적 명령 금지.

### 범위 외 (Out of Scope)

- **bandit(UCB/Thompson) recipe 선택** — v1은 ε-greedy. bandit은 운영데이터 본 뒤 v2.
- **TC에 추상축 taxonomy 내장** — v1은 에이전트가 매핑(LLM-free 유지). 시스템 내장은 후속 결정.
- **분산 다중 워커 병렬 진화** — v1은 단일 워커 sequential(현재 cq 노트북 워커).
- **OpenEvolve 등 외부 프레임워크 도입** — 중복·충돌로 명시적 배제. 아이디어만 차용.
- **자동 saturation 종료** — 노력예산 D + 보편탐지로 충분.

## 리스크

| 리스크 | 심각도 | 초기 대응 |
|--------|--------|----------|
| 새 recipe 저술 train.py 버그(학습 안 됨) | 중 | E16 실패도 evidence, self-correct. py_compile + cascade 스크리닝 |
| 웹검색 noise → 무의미 recipe | 중 | corpus 기존 대조 + 정체∧티어소진 때만 + cap |
| 추상축 매핑 자의성(에이전트 판단 변동) | 중 | 매핑을 evidence attribution에 명시 기록 → 사후 감사 가능 |
| 보편이 존재 안 함 → 안 멈춤 | 낮 | E14 노력예산 D fallback("no-universal-yet 종료") |
| ε-greedy가 비싼 ③을 너무 자주 → 비용 | 중 | 사다리(②우선)+정체게이트+웹검색 cap. ε 조절 |
| 단일 워커 sequential throughput | 낮 | k=1 기본, 다중워커는 범위 외(cq 인프라 트랙) |
| LLM-free 순수성 훼손(에이전트=LLM 재유입) | 낮(설계상 의도) | TC는 LLM-free 유지, LLM은 *에이전트 층*에만 = 올바른 자리 |

## 탐구 중 발견한 인사이트

- **탐색은 귀납이 못 하는 일** — "PatchCore의 memory_size와 EfficientAD의 backbone이 같은 노브(capacity)"라는 인식은 귀납이 아니라 개념적 추상화. 외부 prior(에이전트)가 필요 → 탐색·추상매핑은 구조적으로 에이전트 층.
- **우리 lock-in = Novelty Search가 증명한 "기만적 국소최적"** — objective만 좇으면 갇힌다는 게 이론. QD가 해법(셀별 best 아카이브 + 발산).
- **우리는 이미 AlphaEvolve의 3/4** — TC=program DB, 에이전트=LLM 변이연산자, cq=evaluator. 빠진 건 컨트롤러뿐. 프레임워크 도입은 중복·LLM-free 위배 → 자체 lite 조립이 정답.
- **수렴(보편판정)과 발산(novelty)은 당긴다 — QD가 둘 다** — "커버리지=격자완성"으로 읽으면 새 방법을 막음. "아카이브를 발산으로 채우는 anytime"으로 읽으면 양립. 보편을 게이트→보너스로 낮추는 게 핵심 전환.
- **ε-greedy는 v1 충분, 싼 업그레이드 2개가 고효율** — 문헌의 bandit은 과함(YAGNI). 중복거부 + 정체에스컬레이트가 lock-in을 직접 깸, 거의 공짜.
- **티어 사다리가 비용을 자연 cap** — WESE식 "싼 탐색 우선, 비싼 건 최후". 웹검색이 explore∧소진∧정체 교집합에서만 발동.

## 참고 자료

- 확장 대상 idea: `.cq/runtime/ideas/cq-tc-autonomous-experiment-loop.md`, `.cq/runtime/ideas/cq-tc-agentic-novelty-websearch.md`
- 기존 자산: `experiments/bottle_loop/train_{patchcore,efficientad,ae}.py`, `scripts/cq_dispatch.py`, the-commons MCP(tc_knowledge/tc_recent_attempts/tc_ingest_pcq/tc_lineage/tc_get_evidence)
- 직전 실험 결과: `.cq/runtime/state/mvtec_generalization_state.json`(memory↑=보편/img↑=비보편, PatchCore 단일)
- AlphaEvolve 논문: arXiv 2506.13131 / [작동방식](https://www.emergentmind.com/topics/alphaevolve-framework)
- 오픈클론: [OpenEvolve](https://huggingface.co/blog/codelion/openevolve), CodeEvolve(arXiv 2510.14150)
- 이론: Novelty Search & deception, MAP-Elites(Mouret & Clune "Illuminating search spaces"), Quality-Diversity(Frontiers 2016)
- ShinkaEvolve(novelty rejection·bandit), LLaMEA(stagnation 지표), WESE(약한탐색/강한exploit 분리)

---
*Generated by /pi on 2026-05-25*
