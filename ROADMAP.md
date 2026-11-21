# Roadmap

> The proposition is frozen. This roadmap is how we grow into it.
>
> **Everything is an assertion; every judgment is evidence-backed.**

This is a *planning basis*, not a contract. It is anchored to [the philosophy](https://wanghesong2019.github.io/dataquality-agent/docs/philosophy) and re-cut on every release — the proposition does not change, the milestones do.

## How to read this

- **Three axes** = the three axioms. **Four seams** = the four extension points.
- Every milestone names which axis/seam it advances and *why now*. The ordering is the philosophy, not a feature list.
- Confidence: ✅ shipped · 🚧 in progress · 🎯 planned · 🔮 directional.

## The three axes

| Axis | What it means for the roadmap |
|---|---|
| **Axiom 1 — Uniformity of assertion** | One assertion has a declaration, a verdict, and evidence. L0 rules / L1 statistics / L2 semantics are *three ways to compute the same verdict* — so "declarative" must grow up that ladder, not sideways. |
| **Axiom 2 — Evidence first-class** | No conclusion without a structured `Evidence`. Every milestone must thread evidence end-to-end (detect → attribute → remediate → evaluate) before it is called done. |
| **Axiom 3 — Determinism first** | Rules before statistics, statistics before LLM. Every step lands with a deterministic CI gate (P7) *before* any LLM-dependent surface expands. |

## The four seams — status → next

| Seam | What it is | Now | Next |
|---|---|---|---|
| `WarehouseAdapter` | the evidence interface | DuckDB · Postgres | StarRocks / … |
| `Detector` | the assertion | declarative L0 (YAML) · L1/L2 | declarative L1 → L2 |
| `RemediationPolicy` | the remediation assertion | Executor + Critic | richer fix policies / risk taxonomy |
| `CaseStore` / RAG | reuse of evidence | retriever + rerank | memory governance (provenance + validity) |

## Milestones

### Shipped

- **v0.1.0** — pluggable kernel: `WarehouseAdapter` + `DuckDBAdapter`, `Detector` protocol + registry, L0/L1/L2, `dqagent` CLI, `RunStore`, deterministic eval + CI gate. *Axiom 1: the four seams first exist.*
- **v0.1.1** — deferred minors cleared (thresholds wired, no-LLM eval, robustness). *Axiom 3: determinism hardened.*
- **v0.2.0** — the philosophy landed: `Evidence` becomes a structured first-class object; attribution is thinned to a single evidence-consuming LLM call. *Axiom 2: evidence stops being prose and becomes data.*
- **v0.2.1** — measured, not asserted: token blowup fixed, eval flakiness fixed; thin agent 1.000 attribution / ~85k tokens beats the supervisor 0.750 / ~228k. *P7: the thin agent is shipped because it was measured to win, not because it is fashionable.*
- **v0.3.0** — `PostgresAdapter` (first real warehouse) + declarative L0 assertion catalog (YAML → `Detector`). *Axiom 1: the declaration half of an assertion is extracted from code into data; Axiom 2: the evidence interface reaches a real warehouse.*

### Planned (ordered by the philosophy)

- **v0.4.0** 🎯 — declarative **L1** (freshness / volume / distribution / schema / lineage). Requires the historical-baseline-snapshot concept deferred from v0.2. *The "statistics" rung of the L0→L1→L2 ladder.*
- **v0.5.0** 🎯 — declarative **L2** semantic assertions + **memory governance** for the case store (provenance + validity period, killing anti-pattern #6 "memory as RAG"). *The "LLM" rung, landing on evidence, plus the reuse-of-evidence seam gets governance.*
  - **Acceptance — escalation gate**: L2 runs *only* when an assertion's deterministic verifier returns `undecidable` (reason: missing column/table, no baseline snapshot, or a natural-language declaration). The input is an evidence package, the output a structured verdict. "No anomaly found" is a *pass*, never a reason to invoke L2.
  - **Prerequisite**: per-assertion observability — turn the silent `except` in `run_catalog_checks` into an `undecidable(reason=...)` signal (today deferred-minor #5), so the runner can see *which* assertions bailed and escalate exactly those.
- **v1.0** 🔮 — thin platform shell (`dqagent serve` → dashboard + HITL) as a first-class deployment. *The seams stop being a library and become a service.*

## Why this order

- **L0 before L1 before L2** *is* Axiom 3 — "rules before statistics, statistics before LLM". Declarative follows the same ladder: extract the deterministic verdict first, then the statistical, then the semantic.
- **Evidence-first means no layer ships until its anomalies carry `Evidence`** (Axiom 2). We do not bolt attribution onto detection later; each layer is born carrying its own evidence.
- **Each step lands with a deterministic CI gate before the LLM surface expands** (Axiom 3 + P7). Cost-normalized success rate + pass^k, not vibes, decide what ships.

## Guardrails — what the roadmap refuses

These are the [anti-patterns](https://wanghesong2019.github.io/dataquality-agent/docs/philosophy#what-violates-the-philosophy) as a negative roadmap; any milestone that would require one is out of order.

1. No Turing-complete assertion DSL for L0 — YAML expresses "table + column + condition + threshold" only.
2. No SQL dialect translation layer — dialect differences stay inside each detector's reference implementation.
3. No agents-for-the-sake-of-agents — decompose only with evidence that it pays.
4. No blanket metadata preload — the adapter answers on demand (P3).
5. No "fix claimed without re-check" — remediation is verified offline on a cloned warehouse.
6. No memory-as-RAG — a case store must carry provenance and a validity period.

## How this evolves

- **The proposition is frozen**, like Flink's "everything is a stream".
- **Axioms can grow** — e.g. someday "contract" (schema contract) becomes a fourth kind of assertion.
- **Principles iterate** with practice; each change is recorded in the changelog with its *why*.
- **Anti-patterns accrete per release** — every newly discovered way to violate the philosophy is appended here.
