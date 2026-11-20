from dataquality_agent.adapters import DuckDBAdapter
from dataquality_agent.data.injector import Injector
from dataquality_agent.detection.rules import check_duplicate, run_consistency_checks, run_rule_checks


def test_clean_warehouse_no_false_positive(mini_warehouse):
    """干净数据（含 canceled 订单的合法 null 交付日期）不该有任何误报。"""
    conn = Injector(mini_warehouse).connect()
    assert run_rule_checks(DuckDBAdapter(conn)) == []


def test_detect_duplicate(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    adapter = DuckDBAdapter(conn)
    inj.run(conn, [{"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 1}])
    assert "duplicate" in [a.type for a in run_rule_checks(adapter)]


def test_duplicate_evidence_structured(mini_warehouse):
    """注入重复键后，异常证据应为结构化 Evidence（query + 命中行样本，封顶 20）。"""
    from dataquality_agent.models import Evidence

    inj = Injector(mini_warehouse)
    conn = inj.connect()
    adapter = DuckDBAdapter(conn)
    inj.run(conn, [{"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 1}])
    anomalies = check_duplicate(adapter, "orders", ["order_id"])
    assert anomalies, "注入重复键后应检出"
    ev = anomalies[0].evidence
    assert isinstance(ev, Evidence)          # 不再是 str
    assert ev.query and ev.query.strip()     # query 非空
    assert ev.rows, "必须抓到命中行样本"      # rows 非空
    assert len(ev.rows) <= 20                # 封顶
    assert "重复" in anomalies[0].summary    # summary 兼容旧文本


def test_all_l0_anomalies_carry_evidence(mini_warehouse):
    """迁移后，所有 L0 规则（含跨表一致性）的 fail 异常都带结构化 Evidence。"""
    from dataquality_agent.models import Evidence

    inj = Injector(mini_warehouse)
    conn = inj.connect()
    adapter = DuckDBAdapter(conn)
    inj.run(conn, [
        {"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 1},
        {"type": "orphan", "child_table": "order_items", "parent_table": "orders",
         "parent_pk": "order_id", "child_fk": "order_id", "n": 1},
        {"type": "null_rate", "table": "orders", "column": "order_delivered_customer_date",
         "status_col": "order_status", "status_value": "delivered",
         "key_cols": ["order_id"], "n": 1},
    ])
    conn.execute("UPDATE order_items SET price = -5.0 WHERE order_id = 'o1'")  # negative
    conn.execute("UPDATE payments SET payment_value = 999.0 WHERE order_id = 'o1' AND payment_sequential = 1")  # amount_mismatch
    conn.execute("INSERT INTO reviews VALUES ('r9', 'o3', 1, '', '', '2018-01-05 00:00:00', '2018-01-06 00:00:00')")  # state_conflict
    conn.execute("INSERT INTO geolocation VALUES ('01001', -23.6, -46.7, 'campinas', 'SP')")  # zip_inconsistency

    anomalies = run_rule_checks(adapter) + run_consistency_checks(adapter)
    assert anomalies, "注入后应有多条异常"
    for a in anomalies:
        assert isinstance(a.evidence, Evidence), f"{a.type} 证据不是 Evidence"
        assert a.evidence.query.strip(), f"{a.type} 的 query 为空"
        # 行型规则正常采样到 rows；跨表 join 型在命中实体被并发删除时 rows 可为空（Review Focus #2），此时靠 expected/actual
        assert a.evidence.rows or (a.evidence.expected or a.evidence.actual), f"{a.type} 无任何证据内容"


def test_sample_offending_swallows_adapter_errors():
    """采样查询自身报错时返回空列表，不崩整次巡检（Review Focus #1 单检测器隔离）。"""
    from dataquality_agent.detection.rules import sample_offending

    class BoomAdapter:
        def describe_table(self, table):
            return {"a": "INTEGER"}

        def execute(self, sql, max_rows=None):
            raise RuntimeError("boom")

    assert sample_offending(BoomAdapter(), "orders", "a < 0") == []


def test_detect_orphan(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    adapter = DuckDBAdapter(conn)
    inj.run(conn, [{"type": "orphan", "child_table": "order_items", "parent_table": "orders",
                    "parent_pk": "order_id", "child_fk": "order_id", "n": 1}])
    assert "orphan" in [a.type for a in run_rule_checks(adapter)]


def test_detect_negative_price(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    adapter = DuckDBAdapter(conn)
    conn.execute("UPDATE order_items SET price = -5.0 WHERE order_id = 'o1'")
    assert "value_range" in [a.type for a in run_rule_checks(adapter)]


def test_consistency_checks_clean(mini_warehouse):
    """干净数据不该有跨表一致性误报（金额/状态/邮编/FK 全部一致）。"""
    conn = Injector(mini_warehouse).connect()
    assert run_consistency_checks(DuckDBAdapter(conn)) == []


def test_detect_amount_mismatch(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    adapter = DuckDBAdapter(conn)
    conn.execute("UPDATE payments SET payment_value = 999.0 WHERE order_id = 'o1' AND payment_sequential = 1")
    anomalies = run_consistency_checks(adapter)
    assert "amount_mismatch" in [a.type for a in anomalies]
    a = next(x for x in anomalies if x.type == "amount_mismatch")
    assert a.evidence.rows, "amount_mismatch 应采样到 mismatch 的订单行"
    assert a.evidence.query.strip()


def test_detect_state_conflict(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    adapter = DuckDBAdapter(conn)
    conn.execute("INSERT INTO reviews VALUES ('r9', 'o3', 1, '', '', '2018-01-05 00:00:00', '2018-01-06 00:00:00')")
    assert "state_conflict" in [a.type for a in run_consistency_checks(adapter)]


def test_detect_zip_inconsistency(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    adapter = DuckDBAdapter(conn)
    conn.execute("INSERT INTO geolocation VALUES ('01001', -23.6, -46.7, 'campinas', 'SP')")
    assert "zip_inconsistency" in [a.type for a in run_consistency_checks(adapter)]


def test_detect_orphan_fk_product(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    adapter = DuckDBAdapter(conn)
    conn.execute("DELETE FROM products WHERE product_id = 'p1'")
    assert "orphan" in [a.type for a in run_consistency_checks(adapter)]


def test_null_rate_threshold_controls_detection(mini_warehouse):
    """null_rate_threshold 应真正控制 delivered 交付日期空值检查（不再是死配置）。"""
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    adapter = DuckDBAdapter(conn)
    # 1 个 delivered 订单交付日期置空 → delivered 组 null 率 50%
    inj.run(conn, [{"type": "null_rate", "table": "orders", "column": "order_delivered_customer_date",
                    "status_col": "order_status", "status_value": "delivered",
                    "key_cols": ["order_id"], "n": 1}])
    assert "null_rate" in [a.type for a in run_rule_checks(adapter, null_rate_threshold=0.05)]
    assert "null_rate" not in [a.type for a in run_rule_checks(adapter, null_rate_threshold=0.99)]
