# The Commons

> A cross-user match-maker for ML experiments, backed by an evidence library.
>
> Books are written in the **pcq** format. Most are produced by the **cq** service.
> The Commons keeps them — and tells you which experiment to run next.
> PI Lab operates the platform; contributors earn attribution and mileage.

---

## What This Is

A PI Lab–operated library of *raw experiment evidence* (`run_record.json` and its
kin), contributed by humans and agents, organized for discovery, and preserved
including **null and negative results** — the kind of evidence that disappears
everywhere else.

Wikipedia proved that a collective body of knowledge can be built by humans and
bots working under the same audit trail. The Commons applies that model to
machine-learning experiments — but the corpus is the *mechanism*, not the end.
The end is the **match-maker**: given a problem and the resources at hand, it
ranks the **next experiment that most reduces uncertainty about that problem
region** — an *information-gain* objective, not an expected-metric leaderboard.
This is why null and negative evidence is first-class: "what did not work"
narrows the search space as much as what did.

The library exists so the match-maker is good. The match-maker is the role;
the library is how it earns its recommendations.

---

## The Three Layers

```
┌────────────────────────────────────────────────────────────┐
│  pcq          Format (the book)                             │
│               Apache-2.0 contract for ML experiments        │
└────────────────────────────────────────────────────────────┘
                       ↓ books are written
┌────────────────────────────────────────────────────────────┐
│  cq           Press (the printing house)                    │
│               Managed orchestration: distributed GPU,       │
│               queue, dashboards, agent loop                 │
└────────────────────────────────────────────────────────────┘
                       ↓ books arrive
┌────────────────────────────────────────────────────────────┐
│  the Commons  Library (this project)                        │
│               Collects · classifies · preserves · serves    │
│               Humans and agents contribute as equals        │
└────────────────────────────────────────────────────────────┘
                       ↑
                       ↑ books may also arrive from local, CI,
                         or third-party runners — not only cq
```

Each layer stands alone:
- `pcq` works without `cq` or The Commons (just a format).
- `cq` works without The Commons (private mode).
- The Commons accepts evidence from any pcq-compliant source, not only cq.

---

## How Knowledge Flows — The Match-Maker Pattern

The three layers exchange information through a single, narrow protocol.
Each layer knows only what it needs to:

```
human + agent
   │
   │  "solve this problem"
   ▼
┌────────────────────────────────────────────────────┐
│ pcq      Format (contract)                          │
│          • the agreed shape of a "job"              │
│          • does not know who runs it                │
└────────────────────────────────────────────────────┘
   │                                            ▲
   │  standard job shape                        │  evidence (run_record.json)
   ▼                                            │
┌────────────────────────────────────────────────────┐
│ cq       Executor and reporter                      │
│          • registers and manages workers            │
│          • reports worker specs to The Commons      │
│          • asks The Commons for recommended jobs    │
│          • runs on the user's machine, on the data  │
│          • sends evidence back to The Commons       │
│          • does not know why a job was recommended  │
└────────────────────────────────────────────────────┘
   ↕  (specs / recommendations / evidence)
┌────────────────────────────────────────────────────┐
│ the     Match-maker (library is the mechanism)      │
│ Commons • indexes worker specs from cq              │
│         • accumulates evidence (the library)        │
│         • ranks the next job by information gain —  │
│           negatives narrow the search space         │
│         • never sees the user's data files          │
│         • recommendations grow sharper as the       │
│           corpus grows                              │
└────────────────────────────────────────────────────┘
```

### Single Responsibility — what each layer knows and does not know

| Layer | Knows | Does not know |
|---|---|---|
| **pcq** | The format | Who executes, what data, why a job was chosen |
| **cq** | Workers, data, execution, evidence | The reasoning behind recommendations, other users' results |
| **the Commons** | Accumulated evidence, all worker spec metadata, recommendation logic | The user's data files, real-time worker load |

### What lives where

| Asset | Where it stays |
|---|---|
| User's data files | **On the user's machine only.** Never transmitted. |
| Model and training code | On the user's machine. cq pulls it locally. |
| Evidence (config, metrics, manifest, run_record, validation) | Leaves only as evidence — to The Commons. |
| Worker specs (CPU/GPU/RAM, not contents) | Reported once at worker registration, refreshed on change. |
| Recommendations | Stay in The Commons; cq fetches them on demand. |

This separation is what makes The Commons safe for sensitive domains
(healthcare, finance, regulated industries). The library never learns what
your data *contains* — only what *worked* on which *kind* of machine.

### Loose coupling — recommendation, not command

The Commons does not *command* cq. cq *asks*; The Commons *advises*; the
human or agent *chooses*; cq *executes*.

```
cq → Commons:   "given this problem and this worker, what do you recommend?"
Commons → cq:   "here are N candidates, each with evidence-based estimates"
human/agent:    selects one (or asks for more)
cq:             runs it
cq → Commons:   "here is the resulting evidence"
```

This is advisor-as-service, not control plane. Either side can be offline
without breaking the other.

### cq is not the only orchestrator

The diagram puts cq in the middle, but the contract is designed to open
in phases:

- *Code execution* is already independent of cq — a local `pcq run`, a CI
  pipeline, a research cluster, or any third-party orchestrator can produce
  pcq-compliant evidence today.
- *Ingestion path* into The Commons is staged. In the first phase, evidence
  reaches The Commons through cq's authenticated gateway (regardless of what
  ran the experiment). In later phases, the ingestion surface itself opens
  to direct deposit from third-party runners.

This phased opening keeps the public-library promise — anyone may eventually
contribute through any pcq-compliant path — without forcing the operational
cost of a public ingestion API on day one.

---

## Multi-step Investigation Cycle

The Commons is not a one-shot recommender. Solving a real problem usually
takes a *sequence* of small experiments — explore the data, propose
candidates, run them, evaluate, refine. The Commons leads that loop.

> Externally, think of it as a *sommelier for ML problems*.
> Internally, it behaves more like a *research guide* — pacing investigation
> step by step.

### The cycle

```
user / agent
   │
   │  "predict signup probability from this CSV"
   ▼
the Commons → cq :  "first, profile the data —
                     rows, dtypes, missingness, class balance"
   │
   ▼   (cq runs locally on the user's machine; evidence returns)
   │
the Commons → cq :  "candidate recipes for this shape + your hardware:
                       1) LightGBM    (~3 min, AUC 0.84 ± 0.02 on similar shapes)
                       2) XGBoost     (~5 min, AUC 0.83 ± 0.02)
                       3) TabPFN      (~1 min, strong on small data)
                       4) sklearn RF  (~2 min, baseline)"
   │
   ▼   (human or agent picks; cq runs the selected jobs)
   │
the Commons :        evaluate evidence, propose the next round —
                       "TabPFN won at AUC 0.87. Tune n_estimators next?
                        Or stack TabPFN + LightGBM?"
   ↺ loop until the answer is good enough
```

Every step in the cycle is a **separate pcq job**. The Commons does not
fuse them into a black box — each step has its own `cq.yaml`, its own
`run_record.json`, and its own audit trail. Inspecting why the match-maker
went one way and not another is always possible.

### Each step is a job

| Step | What it measures | Where evidence flows |
|---|---|---|
| Profile | data shape, dtypes, missingness, class balance | run_record → Commons |
| Candidate run | recipe-specific metrics (AUC, RMSE, latency, memory) | run_record → Commons |
| Compare / lineage | cross-run diff, parent chain | derived view → Commons |
| Tuning round | search trajectory, best-so-far | run_record → Commons |

### Two-way growth — reading and writing share the corpus

```
                  ┌──────────────────────────┐
  user request    │   the Commons             │
  ───────────▶    │   (match-maker)           │ ◀── reads corpus
                  └──────────────────────────┘
                            │
                            ▼  recipe / candidate jobs
                  ┌──────────────────────────┐
                  │   cq (execution)          │
                  └──────────────────────────┘
                            │
                            ▼  evidence
                  ┌──────────────────────────┐
                  │   the Commons             │ ◀── writes corpus
                  │   (library)               │
                  └──────────────────────────┘
                            ↻
```

Reading and writing happen on the *same* corpus. As the match-maker advises
more cycles, the library accumulates more evidence; as the library grows,
the match-maker's advice gets sharper. This is the same loop that gave
Wikipedia its momentum, applied to ML experiments.

### Failure is fuel

A run that *fails* — out-of-memory, diverged loss, accuracy below baseline,
exceeded the time budget — is not a wasted job. It is the **first thing the
next cycle needs to know**. The Commons preserves null and negative results
with the same standing as successful runs, and feeds them into the next
round of recommendations.

What didn't work on your hardware narrows the search just as much as what
did.

---

## Founding Principles

1. **Raw evidence is a first-class citizen.** Not prose summaries, not curated
   reports — the `run_record.json` itself is the unit of knowledge. Prose grows
   on top.

2. **Null and negative results are preserved.** What didn't work is often more
   informative than what did. Other archives lose this.

3. **Humans and agents are equal participants.** Same surface, same audit trail.
   Different responsibility model: an agent's actions are attributable to its
   operator. Reputation accrues to both. (The Wikipedia + bots model.)

4. **Contribution is the membership.** Anyone who contributes evidence — whether
   through cq, locally, in CI, or via a third-party runner — is a member of The
   Commons. No gatekeepers between researcher and shelf.

5. **The corpus is a durable PI Lab asset.** PI Lab owns and operates the
   collected corpus; contributors receive attribution and mileage for what
   they deposit. Full corpus export exists for disaster recovery and to avoid
   single-database lock-in — an operational durability property, not an
   anti-privatization promise (see Governance).

---

## Why a Separate Project

The Commons is not a feature of cq. It is a library, not a press.

- Different **asset model**: the collected corpus is a PI Lab asset; the code
  is open source (Apache-2.0). Contributors get attribution + mileage, not
  evidence ownership.
- Different **development cadence**: slow, durable infrastructure — not a SaaS
  release schedule.
- Different **identity**: cq must be usable without contributing; The Commons
  is the cross-user knowledge layer behind it.
- Different **durability invariant**: the corpus is fully exportable for
  disaster recovery / migration (operational, not anti-privatization).

These differences hold even while a single operator (currently PI Lab) runs
both layers. Holding them in one project would force compromises — license
mixing, cadence collisions, identity drift — that hurt all three layers.

---

## The Exchange (How Evidence Arrives)

The cleanest path to contribution is the **cq** service:

> **"Run your experiments on your own GPU through cq's orchestration.
>  In return, the resulting evidence flows into The Commons."**

- cq does not own users' GPUs. It coordinates them.
- Users keep control of code, data, and model weights. Only the *evidence*
  (config, metrics, manifest, run_record, validation_report) flows.

### Two contribution modes — a single binary, no privacy tiers

- **public** (default, free tier) — the standard evidence record is published
  into The Commons. The pcq format and the ingestion layer **systematically
  exclude** raw samples, raw images, raw text, personal identifiers, and
  precise sample counts (quantized to bands). Statistical moments, shape,
  schema, config, metrics, intent, and worker spec are always included.
- **private** (paid tier) — evidence is not sent to The Commons at all.
  cq runs the experiment and reports back only to the user.

There is no third option. Contributors do not decide *what* to share, only
*whether* to share. The "what" is defined and enforced at the format and
ingestion level — this is what makes The Commons safe for sensitive domains
(healthcare, finance) without requiring per-record disclosure judgments.

Direct contribution (without cq) is also a first-class path: any pcq-compliant
run can be deposited into The Commons through a public ingestion surface (TBD).

---

## Reciprocity — Contribution as Mileage

The Commons is not a charity drop-off and it is not a subscription. It is a
reciprocal ecosystem:

```
contribute evidence  →  earn mileage  →  unlock advanced advisor capability
       ↑                                                       ↓
       └────── better experiments produce better evidence ─────┘
```

Mileage is earned, not bought. The strongest source of mileage is having
your evidence **cited by other contributors** (`reproduces`, `derives_from`).
That means good evidence — including good null and negative evidence —
naturally accrues value over time.

| Earn | When |
|---|---|
| evidence deposit (public mode, with intent + fingerprint) | base reward |
| evidence deposit (private-domain contributor, intent only) | reduced reward |
| lineage edge declared | small reward |
| curation contribution (tags, classifications) | small reward |
| **your evidence is cited by another contributor** | largest reward |

| Spend | Cost |
|---|---|
| basic search and read | free for everyone |
| standard match-maker recommendations | free for everyone |
| advanced match-maker (multi-step investigation, meta-analysis) | mileage |
| elevated API rate limits | proportional to balance |
| L3 curation rights (see Immutability model) | threshold to unlock |

**Mileage cannot be purchased with money** — this is the anti-Wikipedia hedge.
Paid-tier users have full access regardless of mileage; their contribution
is *funding the infrastructure* rather than supplying evidence. Both tracks
are first-class members of the ecosystem.

The pattern itself is not novel — Stack Overflow reputation, Wikipedia edit
privileges, airline mileage. Earned-credit systems produce healthier
communities than either pure altruism or pure transaction.

---

## Synthetic Evidence — Seed, Not Destination

A library starts empty. To avoid months of cold start, we accept LLM-distilled
**synthetic evidence** into a tier that is clearly separated from real evidence
and designed to retire itself as the corpus grows.

- **Tiered storage.** Real evidence and synthetic evidence live in the same
  library but in different tiers. The match-maker learns from both, but real
  always outweighs synthetic at equal density.
- **Mandatory attribution.** Every synthetic record carries the originating
  model, prompt hash, and generation timestamp. There is no anonymous
  synthetic evidence in the library.
- **Automatic retirement.** When real evidence in the same (problem-cluster,
  recipe) region crosses a threshold, the matching synthetic records are
  marked *deprecated* — they remain in the library for audit, but no longer
  shape recommendations. The corpus moves toward real-dominance on its own,
  without operator intervention.
- **Verification by reproduction.** A contributor who reproduces a synthetic
  prediction promotes it to real (if the result agrees) or contradicts it
  (if it disagrees). Both outcomes are preserved — the system treats
  contradiction as evidence, not as failure.
- **Always labeled.** UI surfaces always show whether evidence (or a
  recommendation) is backed by real, synthetic, or a mix.

Synthetic evidence is the *seed* of the corpus, not its destination. The
system is designed to retire it.

---

## CPU and Idle-Time Contribution

A meaningful share of ML experiments — tabular models, time-series, classical
NLP, hyperparameter sweeps, small AutoML — runs well on CPUs. The Commons is
designed so that **idle CPU time of contributor machines becomes a first-class
resource**, not a poor cousin to GPU runs.

A laptop running overnight on tabular experiments produces evidence as valid as
any GPU run. The library does not rank contributions by hardware.

(See: SETI@home, Folding@home — distributed citizen compute has worked before.
ML experiments are heterogeneous, but pcq's contract makes them tractable.)

---

## What Lives in the Library

Following the library metaphor:

| Library role | The Commons equivalent |
|---|---|
| Cataloging system | Domain · tag · metric-schema ontology |
| Card catalog | Search index (vector + keyword + metadata) |
| Rare-books room | **Null and negative results — permanently preserved** |
| Lending record | Citation and downstream-use tracking (with privacy) |
| Librarians | Curators — humans and agents alike (Wiki + bots) |
| Reading rooms | Discovery UI · lineage browser · comparison views |
| Library cards | Persona attribution — who contributed what |
| Digitization | Importing legacy experiments into the pcq format |
| Inter-library loan | Federation with other commons (future) |

### Intent in the record

A `run_record` carries not only *what happened* but *what was being attempted*.
A minimal three-field intent — `goal` (one of: baseline reproduction, SOTA
challenge, ablation, hyperparameter sweep, exploration), `expected_baseline`,
and `tolerance` — turns a number like "MPJPE 50mm" from an ambiguous reading
into a comparable outcome: success against a reproduction goal, possibly a
failure against a SOTA goal.

This is what makes **null and negative results legible** to the match-maker.
Without intent, a failed run is just a number; with intent, it is a *narrowing
signal* for the next cycle. Intent is optional — records without it are
accepted, but weighted lower in the recommendation corpus. The format lives
in pcq 2.x.

### Immutability model

The library uses a three-layer immutability policy. Wikipedia's *editable*
maps to *curatable* in this context: the evidence itself is immutable for
reproducibility, while classification, lineage, and reputation grow on top
of it.

| Layer | What | Policy |
|---|---|---|
| **L1 immutable** | `run_record`, attribution (who and when), content hash | Cannot be changed, ever |
| **L2 append-only** | Lineage edges (`derives_from`, `reproduces`, `contradicts`, `compared_to`), validation reports, comments | Can be added; cannot be deleted or modified |
| **L3 mutable** | Tags, domain classifications, curation notes, persona reputation scores | Can be edited; change history is preserved |

If PHI is discovered in already-deposited evidence after the fact, L1 records
are preserved but an L3 visibility flag removes them from the active
recommendation corpus — hidden rather than deleted, since deletion would
break downstream lineage edges and undermine the audit trail.

---

## Governance

**Ownership model — PI Lab proprietary platform (Palantir / HuggingFace posture).**
PI Lab owns and operates The Commons and funds its infrastructure. The
**code is open source (Apache-2.0)** — anyone may self-host. The **operated
instance and the collected corpus are PI Lab assets**. Contributors are not
giving up nothing: they receive **attribution and mileage** for what they
deposit (the platform is the vendor's; the contributor's standing accrues to
them — the Palantir model the user chose).

**What this means concretely:**

- The code may be self-hosted under Apache-2.0; the PI Lab–operated corpus is
  PI Lab's asset, not a public-domain commons.
- Contributors get **attribution + mileage**, not evidence ownership or a
  permissive evidence license. There is no contributor data license.
- Access is mediated by the platform (via cq and mileage), not an
  unconditional free public read.
- Full corpus export exists for **disaster recovery, DB-host independence,
  and migration** — an operational durability property. It is *not* an
  anti-privatization or "outlives the operator" guarantee.

**Future governance — at PI Lab's discretion.**
Any evolution of the ownership or access model is a PI Lab business decision,
made when there is data to decide it. No external-foundation or
non-privatization commitment is made or implied.

---

## How We Know v0.1 Works

The first release is judged not by adoption count but by whether the
vision's core promises *actually operate* in measurable, observable events.
Three signals, all defined and committed before launch:

- **Loop closure** — at least one contributor's evidence demonstrably shapes
  a later contributor's recommendation (evidence ID appears in the *근거
  evidence IDs* of a subsequent recommendation response).
- **Synthetic retirement** — at least one synthetic record is auto-retired
  because real evidence accumulated in the same cluster.
- **Verification by reproduction** — at least one synthetic prediction is
  reproduced by a user, resulting in a *promote* (agreement) or
  *contradicts* (disagreement) event. Both outcomes count.

If **all three** events occur within the first **three months** after
launch, the vision is doing what we said it would. If only some occur,
v0.1 stays in place and focuses on the missing axis. If **none** occur,
the default response is to revise the vision — not blame the
implementation.

Every recorded event is labeled by *outreach origin* (internal / external).
At least one event from an external contributor is what we call a
*strengthened success* — proof that the loop works outside the team that
built it.

---

## Current Status

| Component | State |
|---|---|
| Format (`pcq`) | Released — `uv add pcq` (1.x). pcq 2.x is a TC-side **proposal** ([`docs/pcq-2.x.md`](docs/pcq-2.x.md)), **not canonical** — canonical 2.x is defined by pcq `spec/` and vendored by TC (unresolved: `content_hash` vs v4.4 `attribution` key collision). |
| Press (`cq`) | Operating — PI Lab managed |
| **Library (`The Commons`)** | **v0.1 in development — backend scaffolding complete, 184 tests passing** |

What exists now (private repo, alpha):

- Python 3.12 + FastAPI service with `/health`, `/ingest`, `/evidence/{id}`, `/recommend`
- PostgreSQL 16 + pgvector schema (7 tables, HNSW vector index)
- Hybrid retrieve-and-rerank match-maker wired to Gemini Embedding 2 + Gemini 2.5 Flash
  — note: the v0.1 listwise rerank scores expected fit; it is a **placeholder**
  for the information-gain objective (negatives-aware ranking lands in a later cycle)
- Synthetic-tier evidence + auto-retirement worker + reciprocity event store
- K1→K2 narrative end-to-end test produces a `success` 3-event verdict
- Live integration tests pass against real PostgreSQL and real Gemini API

What is **not** yet live: public ingestion endpoint, hosted deployment, the
mileage/attribution terms, an external onboarding flow. Those are M4 (CQ
integration) and launch tasks.

**On reproducibility (R8 anti-overclaim):**

> pcq makes evidence reproducible, not execution-attested.

The pcq Reproducibility Pack (`code` / `seeds` / `data_ref`, [pcq SPEC.md](https://github.com/playidea-lab/pcq/blob/main/spec/SPEC.md)) records *what code, seeds, and data were used* in a content-addressed form. It does **not** prove that the recorded code actually ran to produce the recorded outputs — causal attestation (TEE quotes, SLSA provenance, sigstore signatures) is a separate substrate that TC does not currently consume. Match-maker decisions on `promote` / `contradicts` events treat reproduction as a *signal*, not a proof.

**Known v0.1 limitations (정직 표기 — v0.2 정정 대상):**
- **L2 immutability is policy-level**, not DB-enforced. `reciprocity_event`,
  `retirement_audit`, `lineage_edge` are append-only by convention; no trigger
  or grant prevents UPDATE/DELETE. (v0.2 ops cycle.)
- **Operator (PI Lab) mutation has no audit trail**. Governance is
  proprietary-platform (Palantir posture), so operator changes are policy-
  permitted, but mutation detection relies on the corpus-export round-trip
  release gate — there is no continuous tamper-detect. (Separate
  governance-honesty cycle.)
- **Embedding staleness has no automatic recompute** trigger. The
  `embedding_template_ver` column tracks the template version, but a model
  bump leaves prior embeddings in place until re-ingest. (v0.2.)
- **lineage_edge stored but not read by match-maker**. From v0.1 envelope
  accepts `lineage` (derives_from / reproduces / contradicts / compared_to)
  and persists to `lineage_edge` table, but ranking does not consume it.
  (v0.2 lineage-aware ranking.)
- **Reproducibility Pack stored but not read by match-maker**. From v0.1
  pcq `code` / `seeds` / `data_ref` are accepted, stored, and integrity-
  hashed, but match-maker ranking does not consume them. (v0.2 reproduce-
  verify before promote: matching content_sha256 ⇒ promote signal,
  mismatch ⇒ contradicts event; trigger/sampling/tolerance TC own design.)
- **PHI-stripped matchmaker policy absent**. When `data_ref` is present
  with `content_sha256=None` (PHI dual-gate), the record is hash-identical
  to one where `data_ref` is fully absent — these are indistinguishable
  via hash alone. v0.2 marks such records as "reproduce-verify not
  possible" via presence inspection of `data_ref.uri`.

---

## Development (v0.1)

### Stack

- **Python 3.12+** with `uv` (no `pip install`)
- **FastAPI** + Pydantic 2
- **PostgreSQL 16** with `pgvector` extension
- **psycopg 3** async + raw SQL
- **Gemini Embedding 2** (text/multimodal-ready) + **Gemini 2.5 Flash** (listwise rerank)
- **PyJWT** for CQ-issued JWT verify
- **pytest** + **ruff**

### Quick start

```bash
# 1. clone + install
git clone https://git.pilab.co.kr/pi/tc.git && cd tc
uv sync

# 2. env (.env)
cp .env.example .env
# GOOGLE_API_KEY=...   # for /recommend; integration tests skip without it

# 3. PostgreSQL with pgvector
docker compose up -d
uv run python -m the_commons.db.migrate

# 4. unit suite (no external deps)
uv run pytest tests/unit -q

# 5. integration suite (needs DB + optionally Gemini key)
uv run pytest tests/integration -q

# 6. dev server
uv run uvicorn the_commons.main:app --reload
# → http://127.0.0.1:8000/docs (OpenAPI)
```

### Project structure

```
src/the_commons/
├── api/            HTTP handlers (health / ingest / evidence / recommend)
├── auth/           CQ-issued JWT verify
├── db/             psycopg async pool + SQL migrations
├── library/        L1 immutable evidence store, content hash, L3 visibility
├── ingestion/      PHI blocker, attribution validator, cluster impact
├── matchmaker/     serializer (template v1) + retriever + reranker + composer
├── reciprocity/    loop_closure / promote / contradicts event store + verdict report
├── retirement/     cluster density worker, deprecate policy
├── llm/            EmbeddingProvider + LLMReranker protocols, Gemini impls, cost meter
└── seed/           synthetic_generator (LLM-distilled) + recipe_catalog
```

### API surface (v0.1, internal only)

All endpoints require a CQ-issued Bearer JWT (`Authorization: Bearer <jwt>`).

```
GET  /health                  liveness + version
POST /ingest                  pcq 2.x evidence → store + cluster impact
GET  /evidence/{evidence_id}  L1 immutable record (synthetic or real)
POST /recommend               query → top-N candidates + corpus_context
```

`/ingest` runs the full pipeline: PHI block → attribution validate → schema
parse → store insert → promote/contradicts event recording → retirement
sweep when `real_count ≥ RETIREMENT_REAL_THRESHOLD`.

`/recommend` runs serialize → embed → pgvector retrieve top-K → LLM listwise
rerank → compose, and records one `loop_closure` event per cited evidence_id.

### Testing strategy

- **`tests/unit/`** — no external dependencies; in-memory protocol impls
  cover every module. 171 cases.
- **`tests/integration/test_postgres_store_real.py`** — round-trips against
  the actual PostgreSQL + pgvector schema. 9 cases.
- **`tests/integration/test_pgvector_retriever_real.py`** — real HNSW
  cosine search on 1024-dim vectors. 3 cases.
- **`tests/integration/test_gemini_real.py`** — real Gemini API calls
  (auto-skipped when `GOOGLE_API_KEY` is empty). 4 cases, ~10s.
- **`tests/unit/test_k1_k2_narrative.py`** — the full vision loop in a
  single test: synthetic seed → K1 ingest produces promote event → K2
  recommend cites K1 → `build_verdict_report` returns `branch=success`,
  `strengthened=True`.

### Configuration

All knobs live in `.env` and are read through `Settings` (Pydantic):

```bash
DATABASE_URL=postgresql://commons:changeme@localhost:5433/commons
GOOGLE_API_KEY=...
GEMINI_EMBEDDING_MODEL=gemini-embedding-2
GEMINI_RERANKER_MODEL=gemini-2.5-flash
CQ_JWT_ISSUER=cq.pilab.kr
CQ_JWT_AUDIENCE=the-commons
RETIREMENT_REAL_THRESHOLD=3       # real evidence count that triggers synthetic retirement
RETRIEVE_TOP_K=20                  # Stage 1 vector retrieve top-K
RECOMMEND_TOP_N=5                  # Stage 2 rerank top-N
TEMPLATE_VERSION=v1                # serializer template version
```

### Vendor abstraction

`EmbeddingProvider`, `LLMReranker`, `VectorIndex`, `EvidenceStore`,
`ReciprocityEventStore`, `RetirementBackend` are all `Protocol`s with
in-memory and Postgres/Gemini implementations. Swapping Gemini for
DeepSeek-V4, Voyage, or a locally-served Qwen happens at the protocol
layer — no match-maker code changes.

---

## What's Next

The vision is captured. The next concrete steps are not in this README — they
belong in design and planning documents that follow once the vision settles.

Concrete questions still open:
- Exact mileage/attribution terms (earn/spend, attribution scope) — no
  contributor data license; the corpus is a PI Lab asset.
- **Canonical pcq 2.x** — defined in pcq `spec/` (not TC). Includes
  resolving the integrity-hash key collision (`content_hash` must move out
  of `attribution`, which v4.4 uses for actor identity). TC vendors it;
  cq M4 (2.x emission) follows that unification. TC's Evidence/content_hash
  code is frozen until then (no unilateral redefinition).
- Ingestion surface — public API shape, validation pipeline, federation.
- **Mileage algorithm** — earn/spend weights, time decay curve, gaming
  prevention (duplicate detection, persona reputation coupling).
- **Match-maker v0.1** — seed corpus from PI Lab internal experiments, the
  baseline recommendation algorithm, how cycle steps are scored.
- The single internal metaphor — "ML sommelier" (external-facing) and
  "research guide" (internal-facing) both apply; the unified internal
  vocabulary is still being chosen.

These are deferred — solving them prematurely will narrow the library before
it has a chance to find its own shape.

---

## Three Layers, One Sentence

> **pcq writes the books. cq prints them. The Commons keeps them — and tells you which to read next.**
