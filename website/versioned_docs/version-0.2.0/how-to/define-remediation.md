---
sidebar_position: 3
title: Define remediation
description: Teach DataAgent how to turn a diagnosis into a fix, and how risky the fix is.
---

# Define remediation

Remediation turns a root-cause diagnosis into a fix, and — critically — assigns that fix a **risk grade**. The risk grade is what decides whether the fix runs straight through or waits behind a human.

## The contract

```python
class Remediation(BaseModel):
    action_type: str        # fix_sql / add_rule / ticket / alert
    sql_or_suggestion: str  # the fix, or the suggestion
    risk_level: str = "low" # low / medium / high
    anomaly_id: str | None = None

    @property
    def requires_approval(self) -> bool:
        return self.risk_level == "high"
```

- `action_type` declares what kind of response it is, not just "run SQL" — you can emit a ticket or an alert instead of a fix.
- `requires_approval` is **derived from `risk_level`**: anything `high` pauses the pipeline. There is no second switch to keep in sync.

## What makes a fix high-risk

A fix is `high` when it can destroy data: `DELETE`/`UPDATE` on a production table, touching monetary fields, or changing permissions. Reversible fixes — deduplication, correcting a value back into range — stay `low`/`medium` and flow through.

## How remediation works today

In the current release, remediation is the **executor + critic** agent pair:

1. The **executor** proposes a `Remediation` from the diagnosis.
2. The **critic** reviews it and returns a `CriticVerdict` (`passed` + `feedback`); a rejected fix is rewritten once.

To customize *what* fixes are proposed, you edit the executor/critic prompts (in `prompts.py`) or swap the underlying LLM. The `risk_level` you assign is the safety lever.

:::note Roadmap
A first-class `RemediationPolicy` protocol — so you can plug in your own fix logic as a seam, exactly like `WarehouseAdapter` and `Detector` — is on the roadmap for a later release. Today the seam is the prompt + the `Remediation` contract above.
:::
