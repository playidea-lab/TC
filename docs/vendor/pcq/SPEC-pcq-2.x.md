## pcq 2.x Contract

pcq 2.x is a backward-compatible additive extension of 1.x. It introduces three
new top-level fields on `run_record.json` — `intent`, `integrity`, and
`contract_version` — while leaving every 1.x field unchanged.

### `intent` object (optional, all fields null-permitted)

Records the *purpose* of the run before it executes.

```json
"intent": {
  "goal": "baseline_reproduction" | "sota_challenge" | "ablation"
         | "hyperparam_sweep" | "exploration",
  "expected_baseline": { "metric": "<string>", "value": <number> } | null,
  "tolerance": { "direction": "<string>", "margin": <number> } | null
}
```

| Field | Type | Note |
|---|---|---|
| `goal` | closed enum or `null` | Intent of this run |
| `expected_baseline` | `{metric, value}` or `null` | Target metric and threshold |
| `tolerance` | `{direction, margin}` or `null` | Acceptable deviation direction and size |

All three fields are `null`-permitted. An `intent` object where every field is
`null` is valid and identical in effect to `intent: null`. Corpus weight
adjustment for null-intent records is the responsibility of the consuming system
(TheCommons), not pcq.

The `intent` field is **optional** on `run_record.json`. Existing records without
it are valid; readers must treat absence as `null` (backward-compatible with 1.x).

### `integrity` object (top-level, not inside `attribution`)

Records the cryptographic fingerprint of the evidence for immutability
verification.

```json
"integrity": {
  "content_hash": "sha256:<hex>",
  "hashed_fields": [
    "intent",
    "config",
    "metrics",
    "data_fingerprint",
    "worker_spec",
    "attribution.author",
    "attribution.committer",
    "attribution.operator",
    "contract_version"
  ]
}
```

#### hashed_fields — leaf path allowlist (anti-recursion)

`hashed_fields` lists the **exact leaf paths** included in the hash computation.
Object-level wholesale inclusion (e.g. `"attribution"` as a single token) is
**not permitted** — only leaf paths or explicitly named sub-paths are allowed.

**Excluded by design**:
- `attribution.signature` — reserved for Phase 2 cryptographic endorsement;
  excluding it ensures that adding a signature later does not invalidate the
  existing hash.
- `integrity` itself — including the hash in its own input would be recursive.

This anti-recursion rule means a future `attribution.signature` field can be
added without changing the `content_hash` of the underlying evidence.

#### Hash computation

```python
# canonical form: json.dumps over the selected subset, indent=2, sort_keys=True, default=str
subset = {path: resolve(run_record, path) for path in hashed_fields}
canonical = json.dumps(subset, indent=2, sort_keys=True, default=str)
content_hash = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
```

This matches the form used in `src/pcq/contract.py` (`build_integrity_object` / `_atomic_write_json`).
Independent verifiers must use `indent=2` to reproduce pcq's hash byte-for-byte.

The `integrity` field is **optional** on `run_record.json`. Existing records
without it are valid (backward-compatible with 1.x).

### `contract_version` field

```json
"contract_version": "2.0"
```

A string that identifies the evidence form (양식) version, independent of the
package version and MCP tool schema version.

#### Three-axis version mapping

| Axis | Value | Meaning |
|---|---|---|
| Package (PyPI) | `4.x` | `uv add pcq` install target |
| `JSON_CONTRACT_VERSION` | `1` | MCP tool contract (frozen surface) |
| `contract_version` | `"2.0"` | Evidence form (양식) version |

The three axes evolve independently. A PyPI version bump does not imply a
`contract_version` bump. A `contract_version` bump does not imply a
`JSON_CONTRACT_VERSION` bump.

Absence of `contract_version` in a record means the record was produced by
pcq 1.x. Readers must treat absence as `"1.x"` and process the record as valid
1.x evidence.

### R9 — TC envelope contract (NORMATIVE)

pcq `run_record` objects are nested inside a TheCommons-owned wrapper when
submitted to the TC evidence store. The envelope contract is:

```json
{
  "evidence_id": "<string>",
  "tier": "real" | "synthetic",
  "outreach_origin": "<string>",
  "synthetic_source": { ... } | null,
  "pcq_record": {
    <pcq 2.x run_record verbatim>
  }
}
```

Boundary rule:

- `evidence_id`, `tier`, `synthetic_source`, `outreach_origin` — **TC scope**.
  These fields are part of the TC evidence wrapper, not part of pcq 2.x.
- `pcq_record` — the complete pcq `run_record.json` object, unchanged.
- The single seam for producers (e.g. cq M4) is: *build a pcq run_record, then
  place it in the `pcq_record` key of the TC envelope*. Ad-hoc sidecar fields
  on the pcq record itself are forbidden.
- pcq specifies the envelope structure for reference only; the authoritative
  implementation of the wrapper is TC's responsibility.

### R10 — `synthetic` / `tier` are not pcq 2.x fields (NORMATIVE)

`tier`, `synthetic_source`, `evidence_id`, and `outreach_origin` are **not**
fields of pcq 2.x `run_record`. They must never be described as required or
optional fields of the pcq evidence form. Any spec or document that describes
them as pcq fields is incorrect and must be corrected.

pcq records real experiments. Synthetic evidence (LLM-distilled) is a TC
artifact managed entirely by TC's own schema outside of pcq.

### R12 — TC Proposal attribution field mapping (NORMATIVE)

The TC Proposal (`docs/pcq-2.x.md` as of 2026-05-19) introduced three
attribution sub-fields. Their canonical mapping into pcq 2.x:

| TC Proposal field | pcq 2.x canonical | Note |
|---|---|---|
| `attribution.created_at` | Existing `run_record` timestamp (`last_updated_at`, `completed_at`, etc.) | No new field; reuse existing timestamps |
| `attribution.contributor_id` | `attribution.operator` | Identical concept; TC reads `attribution.operator` |
| `attribution.pcq_version` | `contract_version` | Top-level field, not inside `attribution` |

These mappings are normative. TC ingestion must read pcq 2.x records using the
pcq-canonical field names above, not the TC Proposal names.

