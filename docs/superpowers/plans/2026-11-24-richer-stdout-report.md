# Richer stdout report for `dqagent run` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `dqagent run` print a human-readable per-anomaly report (root cause + evidence + remediation + approval status) to stdout, instead of a single `run_id/status` line — and make **all user-facing terminal/report output English**.

**Architecture:** A pure function `format_run_report(state: dict) -> str` renders the serialized LangGraph state into an English text block. `cli.py:_cmd_run` calls it right after `runtime.trigger()`. No new dependencies; the function is I/O-free so it unit-tests in isolation. A preceding i18n task (Task 0) translates the user-visible strings that fill the report's *content*.

**Tech Stack:** Python 3.10+, stdlib only.

**Spec:** No separate spec file — the contract is `src/dataquality_agent/models.py` (exact fields of `Anomaly`/`Evidence`/`Diagnosis`/`Remediation`/`Approval`/`Report`) + `src/dataquality_agent/api/runtime.py` (`PatrolRuntime.get` returns `{"run_id","status","state"}`, `state` recursively serialized to plain dicts via `_serialize`) + ROADMAP Axiom 2 (evidence first-class). See rollout plan T6 prerequisite ①.

## Global Constraints

- **All user-facing terminal/report output is English** (the project is international-facing). Internal comments/docstrings stay Chinese — do not translate them.
- `format_run_report` is a pure function: takes a plain-dict `state`, returns `str`, no I/O, no Pydantic models, no mutation.
- Must surface `Evidence` (`expected`/`actual`/`query`), not just a one-line summary (Axiom 2).
- No new runtime dependencies.
- Handle `None`/empty evidence fields without printing the literal string `None`.
- Commit messages use conventional-commits; append the session's `Co-Authored-By: Claude Code <noreply@anthropic.com>` line.

## Review Focus

1. Empty state (`anomalies == []`) must print `no anomalies detected` and not crash → `test_empty_state`.
2. `awaiting_approval` state (`report is None`, a high-risk remediation present) must not crash and must flag the pending approval → `test_awaiting_approval_without_report`.
3. Mismatched list lengths (anomalies/diagnoses/remediations) must not IndexError — zip-with-truncation is the contract → `test_mismatched_lists_no_crash`.
4. `evidence.expected`/`evidence.actual` may be `None` → render a `—` placeholder, never `None` → `test_none_evidence_placeholder`.
5. `evidence.rows` is `list[dict]` → render a bounded preview (≤ 3 rows), never a raw `repr` dump → `test_rows_bounded_preview`.
6. The i18n change must not break eval attribution accuracy (root_cause_category is the judge's key) → Task 0's eval test.

---

### Task 0: i18n — translate user-facing strings to English

**Files (translate user-visible strings only; leave comments/docstrings Chinese):**
- `src/dataquality_agent/cli.py` — `init`/`detect`/`run`/`eval` help text + printed messages.
- `src/dataquality_agent/models.py` — `Diagnosis.root_cause_category` enum values (中文 → English).
- `src/dataquality_agent/data/injector.py` — `ROOT_CAUSE_CATEGORY` mapping + `root_cause` strings.
- `src/dataquality_agent/prompts.py` — LLM prompts (so the model emits English root cause / summary).
- `src/dataquality_agent/detection/{rules,stats,catalog,semantic,runner}.py` — `evidence.expected`/`actual` strings.
- `src/dataquality_agent/eval/{metrics,judge,trajectory}.py` — eval labels (`可逆/数据丢失` → `reversible/data-loss`) and the judge's category comparison.

**Critical coupling (one commit):** `root_cause_category` is the eval judge's comparison key (`judge.py` compares `Diagnosis.root_cause_category` against `InjectedAnomaly.root_cause_category`). Translating it requires updating `models.py` enum + `injector.py` `ROOT_CAUSE_CATEGORY` + `judge.py` **in the same commit**, and a test asserting attribution accuracy stays `1.0` on the Olist eval.

- [ ] **Step 1: Write the failing eval-regression test**

```python
# tests/test_eval.py — assert the i18n change keeps attribution accuracy at 1.0
def test_attribution_accuracy_after_english_enum(...):
    # run the deterministic/LLM eval harness and assert attribution_accuracy == 1.0
    # (reuses the existing eval fixture; the enum is now English in all three places)
```

- [ ] **Step 2: Translate the strings** across the files above (pick consistent English enum values, applied in `models.py` + `injector.py` + `judge.py` together).

- [ ] **Step 3: Run `pytest -q`** — all green, attribution accuracy `1.0`.

- [ ] **Step 4: Commit**

```bash
git add -A src/ tests/
git commit -m "feat(i18n): switch user-facing output to English"
```

---

### Task 1: `format_run_report` pure function (English output)

**Files:**
- Create: `src/dataquality_agent/report_text.py`
- Test: `tests/test_report_text.py`

**Interfaces:**
- Produces: `format_run_report(state: dict) -> str`. `state` is the value of `runtime.get(run_id)["state"]`: a dict whose keys include `anomalies: list[dict]`, `diagnoses: list[dict]`, `remediations: list[dict]`, `approvals: list[dict]`, `report: dict | None`. Each element is a serialized Pydantic model (field names from `models.py`). Align `anomalies[i]`, `diagnoses[i]`, `remediations[i]` by index (zip truncates to the shortest). All labels English.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_report_text.py
from dataquality_agent.report_text import format_run_report


def _anomaly(**kw):
    base = {
        "type": "duplicate", "table": "orders", "column": "order_id", "severity": "high",
        "evidence": {
            "query": "SELECT order_id, COUNT(*) c FROM orders GROUP BY order_id HAVING c > 1",
            "rows": [{"order_id": "1"}, {"order_id": "1"}],
            "expected": "order_id unique", "actual": "14820 duplicates",
        },
    }
    base.update(kw)
    return base


def _diagnosis(**kw):
    base = {"root_cause_category": "dirty data injection", "confidence": 0.95,
            "evidence_chain": [], "evidence": [], "matched_cases": [], "anomaly_id": None}
    base.update(kw)
    return base


def _remediation(**kw):
    base = {"action_type": "fix_sql", "sql_or_suggestion": "DELETE FROM orders WHERE order_id = '1'",
            "risk_level": "high", "evidence": None, "anomaly_id": None}
    base.update(kw)
    return base


def test_completed_report_surfaces_evidence():
    state = {
        "anomalies": [_anomaly()],
        "diagnoses": [_diagnosis()],
        "remediations": [_remediation()],
        "approvals": [],
        "report": {"summary": "found 1 duplicate key, remediation generated", "anomaly_count": 1, "remediation_count": 1},
    }
    text = format_run_report(state)
    assert "[1] duplicate" in text
    assert "orders.order_id" in text
    assert "order_id unique" in text          # evidence.expected surfaced
    assert "14820 duplicates" in text         # evidence.actual surfaced
    assert "dirty data injection" in text     # diagnosis.root_cause_category
    assert "fix_sql" in text
    assert "DELETE FROM orders" in text
    assert "requires approval" in text        # risk_level == "high"
    assert "found 1 duplicate key" in text    # report.summary


def test_awaiting_approval_without_report():
    state = {
        "anomalies": [_anomaly()],
        "diagnoses": [_diagnosis()],
        "remediations": [_remediation()],
        "approvals": [],
        "report": None,                       # 停在审批节点
    }
    text = format_run_report(state)           # 必须不抛异常
    assert "awaiting approval" in text


def test_empty_state():
    state = {"anomalies": [], "diagnoses": [], "remediations": [], "approvals": [], "report": None}
    text = format_run_report(state)
    assert "no anomalies detected" in text


def test_mismatched_lists_no_crash():
    state = {
        "anomalies": [_anomaly(), _anomaly()],
        "diagnoses": [],                     # 比 anomalies 短 → 只按最短对齐
        "remediations": [],
        "approvals": [],
        "report": None,
    }
    text = format_run_report(state)           # 不 IndexError
    assert "[1] duplicate" in text
    assert "[2] duplicate" in text


def test_none_evidence_placeholder():
    state = {
        "anomalies": [_anomaly(evidence={"query": "", "rows": None, "expected": None, "actual": None})],
        "diagnoses": [],
        "remediations": [],
        "approvals": [],
        "report": None,
    }
    text = format_run_report(state)
    assert "None" not in text                 # 不允许打印字面 None


def test_rows_bounded_preview():
    many = [{"order_id": f"ROW{i}"} for i in range(10)]
    state = {
        "anomalies": [_anomaly(evidence={"query": "q", "rows": many, "expected": "e", "actual": "a"})],
        "diagnoses": [],
        "remediations": [],
        "approvals": [],
        "report": None,
    }
    text = format_run_report(state)
    assert "ROW0" in text
    assert "ROW9" not in text                 # 只预览前几行（第 10 行不出现）
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_report_text.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dataquality_agent.report_text'`

- [ ] **Step 3: Implement `format_run_report` in `src/dataquality_agent/report_text.py`**

One function, stdlib only. Per anomaly render a `[i] type  table.column  (severity=…)` header, then indented `expected/actual/root cause/remediation` lines. Join the three lists by index. Footer: `N anomalies total` + `⚠ M high-risk remediations awaiting approval` when any `risk_level == "high"`. Append `report["summary"]` when `report` is not `None`. Use `—` for missing `expected`/`actual`; render `rows` as a ≤3-row preview.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_report_text.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/dataquality_agent/report_text.py tests/test_report_text.py
git commit -m "feat(cli): add format_run_report for human-readable run output"
```

---

### Task 2: Wire into `cli.py:_cmd_run`

**Files:**
- Modify: `src/dataquality_agent/cli.py` (`_cmd_run`, lines 49-61)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `format_run_report(state) -> str` from Task 1; `runtime.get(run_id)["state"]`.
- Produces: `_cmd_run` prints the formatted report before the final `run_id/status` line.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py (append)
def test_run_prints_report(monkeypatch, capsys, tmp_path):
    import dataquality_agent.api.wiring as wiring
    from dataquality_agent import cli

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "olist_orders_dataset.csv").write_text("")

    state = {
        "anomalies": [], "diagnoses": [], "remediations": [], "approvals": [],
        "report": {"summary": "patrol complete", "anomaly_count": 0, "remediation_count": 0},
    }

    class FakeRuntime:
        def trigger(self):
            return {"run_id": "abc12345", "status": "completed"}
        def get(self, run_id):
            return {"run_id": run_id, "status": "completed", "state": state}

    monkeypatch.setattr(wiring, "build_runtime", lambda settings: FakeRuntime())

    rc = cli._cmd_run(type("Args", (), {"dir": str(tmp_path)})())
    out = capsys.readouterr().out
    assert rc == 0
    assert "patrol complete" in out      # report.summary printed
    assert "run_id=abc12345" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_run_prints_report -v`
Expected: FAIL — `"patrol complete"` not in stdout (only `run_id/status` is printed today).

- [ ] **Step 3: Modify `_cmd_run` to print the report**

After `result = runtime.trigger()`, add:
```python
    state = runtime.get(result["run_id"])["state"]
    print(format_run_report(state))
```
with `from dataquality_agent.report_text import format_run_report` at the top of `cli.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py::test_run_prints_report -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all pass (existing 240 + new 7), no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/dataquality_agent/cli.py tests/test_cli.py
git commit -m "feat(cli): print per-anomaly report on dqagent run"
```
