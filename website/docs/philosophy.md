---
sidebar_label: Philosophy
title: Philosophy
description: The worldview behind DataAgent — everything is an assertion, and every judgment is evidence-backed.
---

# Philosophy

> **Everything is an assertion; every judgment is evidence-backed.**

> This is the long-term, cross-version soul of the project. The code, the docs, and every release evolve from it and are constrained by it.

## Why a philosophy

Code can be copied; a philosophy cannot. Unix is remembered for "everything is a file", Flink for "everything is a stream", dbt for "engineering analytics". The strongest of these tools is not any single piece of code, but the worldview you can state in one sentence and no one else can replicate.

DataAgent's differentiation is not "one more detection algorithm". Detection is a 30-year-old commodity — Wang & Strong's 15 dimensions, and GE, Soda and Deequ all map to the same batch. Our differentiation is the **agentic loop around detection** (attribute + remediate + approve + evaluate), and for that loop to hold together under engineering scrutiny, one worldview must run through it.

This page is that worldview. It is a **norm** — the basis on which code review rejects changes — not an essay.

## The proposition, split in two

**Everything is an assertion; every judgment is evidence-backed.**

1. **Everything is an assertion.** The whole quality chain — detect, attribute, remediate, evaluate — is *one kind of thing*, not four separate modules.
2. **Every judgment is evidence-backed.** Wherever there is a conclusion, that conclusion must carry evidence. A conclusion without evidence does not stand.

These two halves produce three axioms.

## Three axioms

### Axiom 1 — Uniformity of assertion

An **assertion** is the unity of three parts:

| Part | What it is | Who defines it |
|---|---|---|
| declaration | "what counts as good": table / column / condition / threshold, declarative | you (free expression) |
| verdict | pass / warn / fail | the framework |
| evidence | when triggered: SQL + offending rows + expected vs actual + lineage | the framework, automatically |

L0 rules, L1 statistics and L2 semantics are **not three things — they are three ways to compute the verdict of the same assertion**. The only difference is how "verdict" is computed:

- L0 rule assertion — deterministic (uniqueness / referential integrity / nulls / value ranges)
- L1 statistical assertion — baseline + deviation (freshness / volume / distribution)
- L2 semantic assertion — LLM reasoning, but it **must land back on evidence**

From this follows the discipline "rules before statistics, statistics before LLM" — no longer a floating slogan, but simply: *try the cheapest verdict first, upgrade only when it cannot decide*.

### Axiom 2 — Evidence is first-class

Evidence is not "a paragraph stuck next to an anomaly" — it is a **structured object**: `query + rows + expected-vs-actual + lineage/blast-radius`.

- Detection evidence: the SQL that triggered the verdict + the offending rows.
- Attribution evidence: the lineage / data slices / similar cases backing a root-cause hypothesis.
- Remediation evidence: the root cause a proposal rests on + the offline re-check result.

**No evidence, no conclusion.** This is the guardrail against LLM hallucination, and the root of "more accurate, more stable": attribution and remediation can be evaluated on whether the evidence actually supports the conclusion.

### Axiom 3 — Determinism first

Rules before statistics, statistics before LLM. The LLM is the **expensive last resort**, invoked only when deterministic criteria cannot decide — and when it enters, its input is an evidence package and its output is an evidence-backed structured conclusion. It is never handed raw access to the warehouse.

This is simultaneously "cheaper" (the optimization target is $/successful-task, not tokens/s) and "more stable" (deterministic results are replayable and CI-gateable).

## Engineering principles

| # | Principle | From |
|---|---|---|
| P1 | **Deterministic replayability** — same snapshot + same assertion → same conclusion | Axiom 3 |
| P2 | **Read-only guardrails** — SELECT-only + whitelist + row caps; the agent proposes, the harness executes | Axiom 3 |
| P3 | **Evidence on demand** — the adapter exposes "what it can query"; it does not preload metadata | Axiom 2 |
| P4 | **Evidence grounding** — the LLM reasons only over evidence already fetched, never freelances | Axiom 2 |
| P5 | **Centralized verification** — a single verification bottleneck, no independent agents running loose | Axiom 2 |
| P6 | **Idempotence** — safe to retry, no double side effects | Axiom 3 |
| P7 | **Evaluation gate** — cost-normalized success rate + pass^k (not pass@k) + holdout | Axiom 2 |

## What violates the philosophy

Any of the following, found in review, violates this philosophy and should be rejected or fixed:

1. **Bare conclusions** — an "anomaly" or "root cause" with no SQL or offending rows attached.
2. **Loose warehouse access** — letting the LLM write and run arbitrary SQL, bypassing the SafeSQL whitelist / row cap.
3. **Agents for the sake of agents** — splitting an agent without evidence that the task decomposes and the saved serial time outweighs coordination cost.
4. **Blanket metadata preload** — dumping the whole schema / lineage / glossary into context up front.
5. **Claiming a fix without re-check** — a remediation that was never applied to a cloned warehouse and re-checked.
6. **Memory as RAG** — a case store that only swaps in and never swaps out, with no provenance and no validity period.

## The four seams, mapped

| Seam | What it is in the philosophy |
|---|---|
| `WarehouseAdapter` | **The evidence interface**: exposes capability (execute / list / describe / row_count), pulls on demand, never dumps metadata |
| `Detector` | **The assertion**: declaration + verdict + evidence |
| `RemediationPolicy` | **The remediation assertion**: root cause → proposal + risk |
| `CaseStore` / RAG | **Reuse of evidence**: a virtual-memory model with provenance + validity |

## How this evolves

- **The proposition is frozen** — like Flink's "everything is a stream", "everything is an assertion; every judgment is evidence-backed" does not change for decades.
- **Axioms can grow** — sub-principles may accrete on top, for example someday "contract (schema contract)" becomes a fourth kind of assertion.
- **Principles can be added or removed** — they iterate with practice, and each change is recorded in the changelog with its *why*.
- **The anti-pattern list tracks releases** — every newly discovered way to violate the philosophy is appended, so its growth is traceable.
