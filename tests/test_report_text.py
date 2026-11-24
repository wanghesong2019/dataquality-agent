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
    assert "No anomalies detected" in text


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


def test_datetime_rows_formatted_cleanly():
    import datetime as dt
    rows = [{"order_id": "o1", "ts": dt.datetime(2018, 1, 1, 10, 0)}]
    state = {
        "anomalies": [_anomaly(evidence={"query": "q", "rows": rows, "expected": "e", "actual": "a"})],
        "diagnoses": [],
        "remediations": [],
        "approvals": [],
        "report": None,
    }
    text = format_run_report(state)
    assert "datetime.datetime" not in text
    assert "2018-01-01 10:00:00" in text
