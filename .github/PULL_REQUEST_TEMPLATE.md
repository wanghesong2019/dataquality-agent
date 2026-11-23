## Summary

<!-- Describe what this PR changes and why. Link the related issue below if applicable. -->

Closes #

## Type of Change

- [ ] **New Warehouse Adapter** (`WarehouseAdapter` implementation)
- [ ] **New Check / Rule** (Declarative L0 YAML assertion or custom `Detector`)
- [ ] **Bug Fix / Accuracy Improvement** (False positive, false negative, or diagnosis fix)
- [ ] **Core Engine / CLI / SafeSQL**
- [ ] **Documentation / Examples / Tests**

## Architecture & Safety Checklist

Please verify that your changes align with **DQAgent**'s engineering principles:

- [ ] **Deterministic First:** Rules and statistical checks are preferred over LLM calls; any LLM step operates strictly over a structured evidence package.
- [ ] **Evidence-Backed:** Any new anomaly or diagnostic path includes verifiable SQL, offending row/aggregate evidence, and expected-vs-actual values.
- [ ] **SafeSQL & Read-Only Compliance:** Runtime inspection queries remain strictly `SELECT`-only, respect table allowlists and `max_rows` caps, and never mutate production data.
- [ ] **Optional Driver Packaging (for Adapters):** New warehouse client packages are declared under `[project.optional-dependencies]` in `pyproject.toml` rather than core `dependencies`.

## Verification

- [ ] Ran `pytest` locally and confirmed all tests pass (including new unit/integration tests for this change).
- [ ] Verified CLI behavior (`dqagent init` / `detect` / `run` / `eval`) if user-facing behavior or config schemas changed.
- [ ] Updated relevant documentation under `website/docs/` or `README.md`.

### Test / CLI Evidence

<!-- Optional: Paste `pytest` summary or sample CLI output demonstrating the change. -->
