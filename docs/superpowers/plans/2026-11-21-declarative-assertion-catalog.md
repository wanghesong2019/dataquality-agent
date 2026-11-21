# Declarative L0 Assertion Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users declare L0 assertions in YAML (unique / not_null / null_rate / value_range / referential) and have the framework compile them into evidence-carrying `Detector`s; migrate the generic hardcoded L0 rules into a default catalog while keeping Olist-specific checks hardcoded.

**Architecture:** A new `detection/catalog.py` holds the `Assertion` dataclass, `load_assertions` (YAML → validated assertions), `default_assertions` (the Olist defaults), and `run_catalog_checks` (dispatch each assertion to the existing `check_*` reference implementations in `rules.py`). `rules.py` is refactored so `run_rule_checks` = catalog checks + hardcoded time/future, and `run_consistency_checks` = amount/state/zip only; `run_detection` gains `assertions_path`.

**Tech Stack:** Python 3.10+, PyYAML, dataclasses, existing `check_*` functions in `detection/rules.py`.

**Spec:** `docs/specs/2026-11-21-v030-design.md` §5 (subsystem 2) + §6 acceptance P3/P4/P5.

## Global Constraints

- `Detector` protocol is `name: str` + `detect(adapter, ctx) -> list[Anomaly]` — the catalog's `build_assertion_detector` is a `Detector` (spec §3).
- `Evidence` model unchanged; declarative anomalies reuse `sample_offending` + `Evidence` (spec §3, §5).
- `WarehouseAdapter` unchanged.
- Only the 5 types `{unique, not_null, null_rate, value_range, referential}` are declarable; Olist-specific `time_inversion` / `future_date` / `amount_mismatch` / `state_conflict` / `zip_inconsistency` stay hardcoded (spec §2, §5.3).
- `where` is a raw SQL fragment (trusted config, dbt-style); no SQL parsing (spec §7).
- No user YAML → behavior identical to today (regression; spec §5.3, §6 P5).
- PyYAML is a **core** dependency (`pyyaml>=6.0`), since YAML is the assertion format.
- Read-only guardrail unchanged (the catalog dispatches to the same `check_*` functions; no new SQL path).
- Existing tests must stay green; the deterministic F1 CI gate (F1 == 1.0) must not regress.

## Review Focus

The input classes / failure modes most likely to bite a person using the catalog:

1. A `null_rate` assertion with a `where` that errors (unbalanced quote, bad column) must not crash the whole run — single-assertion isolation inside `run_catalog_checks`. → Task B3.
2. `value_range` with neither `min` nor `max` must fail-fast at load (`ValueError`), not silently pass. → Task B1.
3. Unknown `type` in YAML must fail-fast with a message naming the type. → Task B1.
4. `referential` with `parent_column` omitted defaults to `child_column`. → Task B1.
5. A custom `severity` on an assertion flows onto the emitted `Anomaly.severity`. → Task B3.

---

### Task B1: `Assertion` model + `load_assertions` (YAML → validated assertions)

**Files:**
- Modify: `pyproject.toml` — add `pyyaml>=6.0` to `[project] dependencies`.
- Create: `src/dataquality_agent/detection/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Produces:
  - `@dataclass Assertion` with fields `name: str`, `type: str`, `table: str | None = None`, `column: str | None = None`, `columns: list[str] | None = None`, `max_rate: float | None = None`, `where: str | None = None`, `min: float | None = None`, `max: float | None = None`, `child_table: str | None = None`, `child_column: str | None = None`, `parent_table: str | None = None`, `parent_column: str | None = None`, `severity: str = "medium"`.
  - `ASSERTION_TYPES = {"unique", "not_null", "null_rate", "value_range", "referential"}`.
  - `load_assertions(path: str | Path) -> list[Assertion]`.

- [ ] **Step 1: Write the failing tests** in `tests/test_catalog.py`

```python
import pytest

from dataquality_agent.detection.catalog import ASSERTION_TYPES, load_assertions


def _write(tmp_path, text):
    p = tmp_path / "assertions.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_all_five_types(tmp_path):
    p = _write(tmp_path, """
version: 1
assertions:
  - name: orders_unique_order_id
    type: unique
    table: orders
    columns: [order_id]
  - name: orders_customer_not_null
    type: not_null
    table: orders
    column: customer_id
  - name: orders_delivered_date_null_rate
    type: null_rate
    table: orders
    column: order_delivered_customer_date
    max_rate: 0.05
    where: "order_status = 'delivered'"
  - name: order_items_price_non_negative
    type: value_range
    table: order_items
    column: price
    min: 0
  - name: order_items_ref_products
    type: referential
    child_table: order_items
    child_column: product_id
    parent_table: products
""")
    a = load_assertions(p)
    assert len(a) == 5
    assert {x.type for x in a} == ASSERTION_TYPES
    assert a[4].parent_column == "product_id"  # defaults to child_column


def test_unknown_type_fails_fast(tmp_path):
    p = _write(tmp_path, "assertions:\n  - name: x\n    type: magic\n    table: t\n")
    with pytest.raises(ValueError, match="magic"):
        load_assertions(p)


def test_value_range_requires_min_or_max(tmp_path):
    p = _write(tmp_path, "assertions:\n  - name: x\n    type: value_range\n    table: t\n    column: c\n")
    with pytest.raises(ValueError, match="min"):
        load_assertions(p)


def test_unique_requires_columns(tmp_path):
    p = _write(tmp_path, "assertions:\n  - name: x\n    type: unique\n    table: t\n")
    with pytest.raises(ValueError):
        load_assertions(p)


def test_duplicate_name_fails_fast(tmp_path):
    p = _write(tmp_path,
        "assertions:\n  - {name: a, type: not_null, table: t, column: c}\n"
        "  - {name: a, type: not_null, table: t, column: c}\n")
    with pytest.raises(ValueError, match="name"):
        load_assertions(p)
```

- [ ] **Step 2: Run to verify fail** — `pytest tests/test_catalog.py -v` → FAIL: `ModuleNotFoundError: No module named 'dataquality_agent.detection.catalog'`.

- [ ] **Step 3: Implement** `catalog.py`

  - Define the `Assertion` dataclass exactly as above.
  - `load_assertions`:
    - `yaml.safe_load(path.read_text(encoding="utf-8"))`; require a mapping with an `assertions` list.
    - Per entry: validate `type ∈ ASSERTION_TYPES` (else `ValueError` naming the type); validate per-type required fields — `unique` → non-empty `columns`; `not_null`/`null_rate`/`value_range` → `table` + `column`; `null_rate` → `max_rate` present; `value_range` → `min` or `max` present; `referential` → `child_table` + `child_column` + `parent_table`. Default `referential.parent_column = child_column`. Reject duplicate `name` (else `ValueError`).
    - Return `list[Assertion]`.

- [ ] **Step 4: Run to verify pass** — `pytest tests/test_catalog.py -v` → PASS.

- [ ] **Step 5: Add `pyyaml>=6.0` to `pyproject.toml` dependencies; commit.**

---

### Task B2: `check_null_rate` gains a `where` clause

**Files:**
- Modify: `src/dataquality_agent/detection/rules.py` (`check_null_rate`).
- Test: `tests/test_rules.py` (add one test).

**Interfaces:**
- Consumes: existing `check_null_rate(adapter, table, column, status_col=None, status_value=None, threshold=0.05)`.
- Produces: `check_null_rate(adapter, table, column, status_col=None, status_value=None, threshold=0.05, where=None)` — when `where` is given it replaces the `status_col`/`status_value`-derived condition; existing call sites in `run_rule_checks` are unchanged and still pass `status_col`/`status_value`.

- [ ] **Step 1: Write the failing test** in `tests/test_rules.py`

```python
def test_check_null_rate_with_raw_where(mini_warehouse):
    from dataquality_agent.detection.rules import check_null_rate

    conn = Injector(mini_warehouse).connect()
    adapter = DuckDBAdapter(conn)
    # delivered 订单交付日期置空 -> where 口径下 null 率 50% 超阈值
    conn.execute("UPDATE orders SET order_delivered_customer_date = NULL WHERE order_id = 'o1'")
    a = check_null_rate(adapter, "orders", "order_delivered_customer_date",
                        where="order_status = 'delivered'", threshold=0.05)
    assert a and a[0].type == "null_rate"
```

- [ ] **Step 2: Run to verify fail** — `pytest tests/test_rules.py::test_check_null_rate_with_raw_where -v` → FAIL: `TypeError: check_null_rate() got an unexpected keyword argument 'where'`.

- [ ] **Step 3: Implement** — add `where: str | None = None`; when `where is not None`, use it as the condition and label the group `"where 组"`; otherwise keep the existing `status_col`/`status_value`/`"1=1"` logic byte-for-byte.

- [ ] **Step 4: Run to verify pass** — `pytest tests/test_rules.py -v` → PASS (all existing + new).

- [ ] **Step 5: Commit.**

---

### Task B3: `Assertion.check` + `run_catalog_checks` (dispatch, evidence, isolation)

**Files:**
- Modify: `src/dataquality_agent/detection/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `check_duplicate`, `check_null_rate`, `check_value_range`, `check_orphan` from `rules.py`; `Anomaly`/`Evidence` from `models.py`.
- Produces:
  - `Assertion.check(self, adapter) -> list[Anomaly]` — dispatch by `type` to the matching `check_*`; apply `self.severity` to each returned anomaly.
  - `run_catalog_checks(adapter, assertions: list[Assertion]) -> list[Anomaly]` — run each `check` in order, catching per-assertion exceptions (isolation), concatenating anomalies.

- [ ] **Step 1: Write the failing tests** in `tests/test_catalog.py`

```python
from dataquality_agent.adapters import DuckDBAdapter
from dataquality_agent.data.injector import Injector
from dataquality_agent.detection.catalog import Assertion, run_catalog_checks
from dataquality_agent.models import Evidence


def test_each_type_detects_with_evidence(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    adapter = DuckDBAdapter(conn)
    # inject: duplicate, orphan, negative price, null customer_id
    conn.execute("INSERT INTO orders SELECT * FROM orders LIMIT 1")
    conn.execute("DELETE FROM products WHERE product_id = 'p1'")
    conn.execute("UPDATE order_items SET price = -5.0 WHERE order_id = 'o1'")
    conn.execute("UPDATE orders SET customer_id = NULL WHERE order_id = 'o1'")
    assertions = [
        Assertion(name="dup", type="unique", table="orders", columns=["order_id"]),
        Assertion(name="orph", type="referential", child_table="order_items",
                  child_column="product_id", parent_table="products"),
        Assertion(name="neg", type="value_range", table="order_items", column="price", min=0),
        Assertion(name="nn", type="not_null", table="orders", column="customer_id"),
        Assertion(name="nr", type="null_rate", table="orders",
                  column="order_delivered_customer_date", max_rate=0.05,
                  where="order_status = 'delivered'"),
    ]
    anomalies = run_catalog_checks(adapter, assertions)
    assert {"duplicate", "orphan", "value_range", "null_rate"} <= {a.type for a in anomalies}
    for a in anomalies:
        assert isinstance(a.evidence, Evidence) and a.evidence.query.strip()


def test_severity_flows_to_anomaly(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    adapter = DuckDBAdapter(conn)
    conn.execute("INSERT INTO orders SELECT * FROM orders LIMIT 1")
    a = run_catalog_checks(adapter, [Assertion(name="dup", type="unique",
                                               table="orders", columns=["order_id"], severity="high")])
    assert a[0].severity == "high"


def test_single_assertion_failure_isolated(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    adapter = DuckDBAdapter(conn)
    conn.execute("INSERT INTO orders SELECT * FROM orders LIMIT 1")
    bad = Assertion(name="bad", type="null_rate", table="orders", column="nope",
                    max_rate=0.5, where="'unbalanced")
    good = Assertion(name="dup", type="unique", table="orders", columns=["order_id"])
    anomalies = run_catalog_checks(adapter, [bad, good])
    assert [a.type for a in anomalies] == ["duplicate"]  # bad skipped, good still runs
```

- [ ] **Step 2: Run to verify fail** — `pytest tests/test_catalog.py -v` → FAIL: `run_catalog_checks` / `Assertion.check` not defined.

- [ ] **Step 3: Implement** `Assertion.check` and `run_catalog_checks`

  - `check` dispatch:
    - `unique` → `check_duplicate(adapter, self.table, self.columns)`
    - `not_null` → `check_null_rate(adapter, self.table, self.column, threshold=0.0)`
    - `null_rate` → `check_null_rate(adapter, self.table, self.column, threshold=self.max_rate, where=self.where)`
    - `value_range` → `check_value_range(adapter, self.table, self.column, self.min, self.max)` (min/max may be `None`)
    - `referential` → `check_orphan(adapter, self.child_table, self.parent_table, self.child_column, self.parent_column)`
  - Apply severity: for each returned anomaly, `a.severity = self.severity`.
  - `run_catalog_checks`: iterate; wrap each `a.check(adapter)` in try/except, `pass` on exception (isolation), extend the result list otherwise.

- [ ] **Step 4: Run to verify pass** — `pytest tests/test_catalog.py -v` → PASS.

- [ ] **Step 5: Commit.**

---

### Task B4: `default_assertions` + `build_assertion_detector`

**Files:**
- Modify: `src/dataquality_agent/detection/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Produces:
  - `default_assertions(null_rate_threshold: float = 0.05) -> list[Assertion]` — the 17 Olist defaults (6 referential + 4 unique + 5 value_range + 2 null_rate).
  - `build_assertion_detector(assertions: list[Assertion]) -> Detector` — a `Detector` with `name = "assertion_catalog"` and `detect(adapter, ctx) = run_catalog_checks(adapter, assertions)`.

- [ ] **Step 1: Write the failing test** in `tests/test_catalog.py`

```python
from dataquality_agent.detection.catalog import build_assertion_detector, default_assertions


def test_default_catalog_covers_generic_l0():
    a = default_assertions()
    assert len(a) == 17
    assert {x.type for x in a} == {"unique", "not_null", "null_rate", "value_range", "referential"}
    # the delivered-date null_rate assertion takes its threshold from the argument
    nr = next(x for x in a if x.type == "null_rate" and x.where)
    assert nr.max_rate == 0.05
    assert next(x for x in default_assertions(0.99) if x.name == nr.name).max_rate == 0.99


def test_build_detector_is_detector(mini_warehouse):
    from dataquality_agent.adapters import DuckDBAdapter
    from dataquality_agent.data.injector import Injector

    conn = Injector(mini_warehouse).connect()
    conn.execute("INSERT INTO orders SELECT * FROM orders LIMIT 1")
    det = build_assertion_detector(default_assertions())
    assert det.name == "assertion_catalog"
    assert "duplicate" in [x.type for x in det.detect(DuckDBAdapter(conn), {})]
```

- [ ] **Step 2: Run to verify fail** — `pytest tests/test_catalog.py -v` → FAIL: `default_assertions` not defined.

- [ ] **Step 3: Implement** `default_assertions` and `build_assertion_detector`.

  `default_assertions` returns, in a stable order, the 17 assertions that today are the generic L0 rules (the delivered-date null_rate uses `max_rate=null_rate_threshold`):
  - unique: `orders[order_id]`, `order_items[order_id, order_item_id]`, `payments[order_id, payment_sequential]`, `reviews[review_id]`
  - referential: `order_items.order_id→orders.order_id`, `order_items.product_id→products.product_id`, `order_items.seller_id→sellers.seller_id`, `payments.order_id→orders.order_id`, `reviews.order_id→orders.order_id`, `orders.customer_id→customers.customer_id`
  - value_range: `order_items.price min=0`, `order_items.freight_value min=0`, `products.product_weight_g min=0`, `reviews.review_score min=1 max=5`, `payments.payment_installments min=1 max=24`
  - null_rate: `orders.order_delivered_customer_date max_rate=null_rate_threshold where="order_status = 'delivered'"` (name `orders_delivered_date_null_rate`), `orders.customer_id max_rate=0` (not_null)

- [ ] **Step 4: Run to verify pass** — `pytest tests/test_catalog.py -v` → PASS.

- [ ] **Step 5: Commit.**

---

### Task B5: Migrate `run_rule_checks` / `run_consistency_checks` and wire `run_detection(assertions_path=...)`

**Files:**
- Modify: `src/dataquality_agent/detection/rules.py` (`run_rule_checks`, `run_consistency_checks`).
- Modify: `src/dataquality_agent/detection/runner.py` (`run_detection`, `_L0Rules`).
- Modify: `tests/test_rules.py` — `test_detect_orphan_fk_product` now expects the orphan via `run_rule_checks`.
- Test: `tests/test_catalog.py` (regression test) + existing suite.

**Interfaces:**
- Consumes: `run_catalog_checks`, `default_assertions`, `load_assertions` (catalog.py).
- Produces:
  - `run_rule_checks(adapter, null_rate_threshold=0.05, assertions=None) -> list[Anomaly]` — runs the catalog (`assertions if assertions is not None else default_assertions(null_rate_threshold)`) plus the hardcoded `check_time_inversion` (×2) and `check_future_date`.
  - `run_consistency_checks(adapter) -> list[Anomaly]` — only `check_amount_mismatch` + `check_state_conflict` + `check_zip_inconsistency`.
  - `run_detection(adapter, detectors=None, *, ..., assertions_path: str | None = None)` — loads `assertions_path` into ctx when given.

- [ ] **Step 1: Write the failing regression test** in `tests/test_catalog.py`

```python
from dataquality_agent.adapters import DuckDBAdapter
from dataquality_agent.data.injector import Injector
from dataquality_agent.detection.rules import run_rule_checks, run_consistency_checks


def test_no_yaml_behavior_unchanged(mini_warehouse):
    """无目录时，run_rule_checks + run_consistency_checks 与现状一致（含 6 条 orphan）。"""
    conn = Injector(mini_warehouse).connect()
    assert run_rule_checks(DuckDBAdapter(conn)) == []          # clean -> no anomalies
    assert run_consistency_checks(DuckDBAdapter(conn)) == []
    # products FK orphan now surfaces via run_rule_checks (catalog), not run_consistency_checks
    conn.execute("DELETE FROM products WHERE product_id = 'p1'")
    assert "orphan" in [a.type for a in run_rule_checks(DuckDBAdapter(conn))]
```

- [ ] **Step 2: Run to verify fail** — `pytest tests/test_catalog.py::test_no_yaml_behavior_unchanged -v` → FAIL: the final assertion fails (the orphan is still in `run_consistency_checks`, not `run_rule_checks`).

- [ ] **Step 3: Implement the migration**

  - `run_rule_checks(adapter, null_rate_threshold=0.05, assertions=None)`:
    ```python
    anomalies = run_catalog_checks(
        adapter,
        assertions if assertions is not None else default_assertions(null_rate_threshold),
    )
    anomalies += check_time_inversion(adapter, "order_delivered_customer_date", "交付日期早于下单日期")
    anomalies += check_time_inversion(adapter, "order_estimated_delivery_date", "预估送达日期早于下单日期")
    anomalies += check_future_date(adapter)
    return anomalies
    ```
  - `run_consistency_checks(adapter)` keeps only `check_amount_mismatch` + `check_state_conflict` + `check_zip_inconsistency`; the 5 `check_orphan` calls are removed (they now live in `default_assertions`).
  - `runner.py`: `_L0Rules.detect` → `rules.run_rule_checks(adapter, ctx["null_rate_threshold"], ctx.get("assertions"))`. `run_detection` gains keyword `assertions_path: str | None = None` and sets `ctx["assertions"] = load_assertions(assertions_path) if assertions_path else None`.
  - Update `tests/test_rules.py::test_detect_orphan_fk_product` to assert `"orphan" in [a.type for a in run_rule_checks(adapter)]` (migration consequence — the orphan moved; detection behavior is unchanged).

- [ ] **Step 4: Run the full suite** — `pytest -q` → all green (218 + new).

- [ ] **Step 5: Commit.**

---

### Task B6 (optional, reachability): CLI + `Settings` expose `assertions_path`

> The acceptance line P3–P5 is met by B1–B5 alone. This task is the natural completion of the user-facing path (`dqagent detect --assertions PATH`); drop it if you want to cut scope.

**Files:**
- Modify: `src/dataquality_agent/config.py` (`Settings.assertions_path: str | None = None`)
- Modify: `src/dataquality_agent/cli.py` (`_cmd_detect` passes `--assertions` through to `run_detection`)

**Interfaces:**
- Consumes: `run_detection(..., assertions_path=...)` (Task B5).

- [ ] **Step 1: Write the failing test** — `tests/test_cli.py`: `_cmd_detect` with `--assertions` pointing at a `load_assertions`-valid YAML runs `run_detection` with that path (assert via a patched `run_detection` capturing `assertions_path`).

- [ ] **Step 2: Run to verify fail** — the CLI has no `--assertions` flag yet.

- [ ] **Step 3: Implement** — add `assertions_path` to `Settings`; add `--assertions` to the `detect` subparser and pass `assertions_path=args.assertions` to `run_detection` in `_cmd_detect`.

- [ ] **Step 4: Run to verify pass** — `pytest tests/test_cli.py -v` → PASS.

- [ ] **Step 5: Commit.**
