from dataquality_agent.detection.stats import zscore_detect, psi, check_freshness, schema_diff


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
