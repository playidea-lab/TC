# The Commons

> An open library of agent-readable ML experiment evidence.
>
> Books are written in the **pcq** format. Most are produced by the **cq** service.
> But the library itself stands apart — anyone can contribute, and everyone can read.

---

## What This Is

A public library of *raw experiment evidence* (`run_record.json` and its kin),
contributed by humans and agents, organized for discovery, and preserved including
**null and negative results** — the kind of evidence that disappears everywhere else.

Wikipedia proved that a collective body of knowledge can be built by humans and
bots working under the same audit trail. The Commons applies that model to
machine-learning experiments — and uses the accumulated evidence to **advise the
next experiment**: which solution fits which problem on which resource.

The library is not just a shelf. It is also a *match-maker*.

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
│ the     Match-maker and library                     │
│ Commons • indexes worker specs from cq              │
│         • accumulates evidence (the library)        │
│         • turns (problem + spec) into recommended   │
│           jobs, backed by past evidence             │
│         • never sees the user's data files          │
│         • recommendations grow more accurate as the │
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

5. **The library outlives any single operator.** Evidence is owned by the
   contributor under a permissive license; the corpus is portable and cannot
   be privatized by any operator, including PI Lab itself (see Governance).

---

## Why a Separate Project

The Commons is not a feature of cq. It is a library, not a press.

- Different **license model**: contributor license for evidence (CDLA-Permissive
  family, exact variant TBD) — distinct from cq's own commercial terms.
- Different **development cadence**: slow, durable infrastructure — not a SaaS
  release schedule.
- Different **identity**: cq must be usable without contributing; The Commons
  must be readable without paying.
- Different **ownership invariant**: the corpus is portable and cannot be
  privatized by any operator (see Governance).

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

**Operating model — PI Lab + community.**
PI Lab operates The Commons and funds its infrastructure. Contributors and
PI Lab are members of the same ecosystem (the Palantir / HuggingFace / GitHub
posture), not customers of a service. The match-maker, the library, and the
press grow together.

**Day-one commitments — these do not require a separate foundation to be true:**

- Evidence is owned by the contributor, not by PI Lab. A permissive
  contributor license (CDLA-Permissive family, exact variant TBD) ensures
  that PI Lab cannot privatize or re-license deposited evidence.
- Reading The Commons is free for anyone, regardless of contribution status.
- Curation and governance decisions are surfaced through public RFCs with
  a public changelog.
- Evidence is **portable by license** — if any operator (including PI Lab)
  ever becomes a poor steward, the corpus can be mirrored and continued
  elsewhere. The library is not a hostage to its operator.

**Future governance — left genuinely open.**
If and when the corpus matures (broad external contributor base, independent
revenue streams, institutional interest), governance can evolve toward more
distributed forms — federated stewardship, an independent foundation, or
arrangements not foreseen today. The shape and timing of that evolution are
decided when there is data to decide them, rather than pre-committed before
the library exists.

This posture is borrowed from early Wikipedia (operated by Wales before
Wikimedia Foundation was established) and early HuggingFace (a single
operator running an open ecosystem with portable contributions). It commits
to *non-privatization* without committing to a *specific* future structure.

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

This repository contains a vision document only.

| Component | State |
|---|---|
| Format (`pcq`) | Released — `uv add pcq` |
| Press (`cq`) | Operating — PI Lab managed |
| **Library (`The Commons`)** | **Vision stage — this README is the only artifact** |

No code yet. No public surface yet. No ingestion endpoint yet. This is the
moment to write down what we are building so that the first lines of code
serve the vision and not the other way around.

---

## What's Next

The vision is captured. The next concrete steps are not in this README — they
belong in design and planning documents that follow once the vision settles.

Concrete questions still open:
- Exact contributor license (specific variant within the CDLA-Permissive family).
- **pcq 2.x specification** — data fingerprint fields, intent format, PHI
  exclusion rules at the format level.
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
