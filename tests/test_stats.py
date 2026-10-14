from dataquality_agent.data.lineage import Lineage
from dataquality_agent.detection.stats import (
    zscore_detect, psi, check_freshness, schema_diff, detect_lineage_break,
    detect_freshness, detect_schema_drift,
)


def test_zscore_detect_normal_and_spike():
    baseline = [100, 105, 98, 102, 99, 101, 103]
    assert zscore_detect(100, baseline, 3.0) is False  # 接近均值，不报
    assert zscore_detect(115, baseline, 3.0) is True   # 3σ 外，报


def test_zscore_detect_constant_baseline():
    # 基线恒定（std=0）时不应误报
    assert zscore_detect(100, [100, 100, 100], 3.0) is False


def test_psi_similar_and_shifted():
    expected = {"credit_card": 80, "boleto": 20}
    assert psi({"credit_card": 82, "boleto": 18}, expected) < 0.1   # 相似，PSI 小
    assert psi({"credit_card": 20, "boleto": 80}, expected) > 0.1   # 漂移，PSI 大


def test_check_freshness():
    # 最新日期 = 当前日期 → 不报停更
    assert check_freshness(["2018-01-01", "2018-01-02", "2018-01-03"], "2018-01-03") is False
    # 最新日期落后当前 3 天 → 报停更
    assert check_freshness(["2018-01-01", "2018-01-02"], "2018-01-05") is True


def test_schema_diff():
    prev = {"a": "INTEGER", "b": "VARCHAR"}
    curr = {"a": "VARCHAR", "c": "INTEGER"}
    changes = schema_diff(prev, curr)
    assert "type_changed:a:INTEGER->VARCHAR" in changes
    assert "removed:b" in changes
    assert "added:c" in changes


def test_lineage_break_detected():
    lineage = Lineage()
    watermarks = {"orders": "2018-10-17", "order_items": "2018-10-17", "daily_metrics": "2018-10-10"}
    anomalies = detect_lineage_break(watermarks, lineage, max_lag_days=1)
    assert any(a.type == "lineage_break" and a.table == "daily_metrics" for a in anomalies)


def test_lineage_break_no_lag():
    lineage = Lineage()
    watermarks = {"orders": "2018-10-17", "order_items": "2018-10-17", "daily_metrics": "2018-10-17"}
    assert detect_lineage_break(watermarks, lineage, max_lag_days=1) == []


def test_detect_freshness():
    watermarks = {"orders": "2018-01-01", "daily_metrics": "2018-01-05"}
    anomalies = detect_freshness(watermarks, "2018-01-06", max_gap_days=1)
    # orders 落后 5 天 → 报；daily_metrics 落后 1 天 → 不报
    assert {a.type: a.table for a in anomalies} == {"freshness": "orders"}


def test_detect_schema_drift():
    curr = {"dwd_orders": {"a": "INTEGER"}}
    expected = {"dwd_orders": {"a": "INTEGER", "b": "VARCHAR"}}
    anomalies = detect_schema_drift(curr, expected)
    assert len(anomalies) == 1
    assert anomalies[0].type == "schema_drift"
    assert "removed:b" in anomalies[0].evidence
