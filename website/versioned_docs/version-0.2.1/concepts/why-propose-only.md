---
sidebar_position: 4
title: Why "propose, never execute"
description: The design decision behind the human approval gate.
---

# Why "propose, never execute"

DataAgent's defining choice is that at runtime it **proposes fixes and never executes them against production**. This is not a missing feature — it is the core safety property, and it shapes everything else.

## The problem with auto-remediation

A data-quality agent that fixes data automatically inherits the blast radius of every mistake:

- **Attribution is probabilistic.** A diagnosis with 0.8 confidence is wrong 1 time in 5. Auto-applying the wrong "fix" *creates* the data-loss incident the tool exists to prevent.
- **Fixes are not reversible.** Deleting a row or nulling a column destroys the original value. There is no `undo` on a production warehouse.
- **The agent is not the owner.** The person who owns the pipeline is accountable for the data. A tool that writes on their behalf removes them from the decision without removing them from the blame.

## What DataAgent does instead

| Instead of… | DataAgent… |
|---|---|
| executing a fix | **proposes** it, with risk grade and evidence |
| trusting attribution blindly | **gates** high-risk fixes behind a human |
| writing to production | **verifies** on a cloned warehouse, offline |
| hoping the fix worked | **re-checks** and reports a remediation success rate |

The loop closes — detect → attribute → propose → approve → verify — but the *write* always belongs to a human.

## The trade-off, stated plainly

This makes DataAgent **safer and slower** than an auto-remediating tool. A high-risk fix waits for a human to be in the loop. That latency is the point: data loss is permanent, and a human's five minutes is cheap insurance against it.

Low-risk, reversible fixes (deduplication, value-range corrections) still flow straight through — the gate is reserved for the small set of fixes that can actually destroy data.
