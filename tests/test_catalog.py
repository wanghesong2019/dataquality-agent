import pytest

from dataquality_agent.adapters import DuckDBAdapter
from dataquality_agent.data.injector import Injector
from dataquality_agent.detection.catalog import (
    ASSERTION_TYPES, Assertion, build_assertion_detector, default_assertions, load_assertions, run_catalog_checks,
)
from dataquality_agent.models import Evidence


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


def test_default_catalog_covers_generic_l0():
    a = default_assertions()
    assert len(a) == 17
    assert {x.type for x in a} == {"unique", "not_null", "null_rate", "value_range", "referential"}
    # the delivered-date null_rate assertion takes its threshold from the argument
    nr = next(x for x in a if x.type == "null_rate" and x.where)
    assert nr.max_rate == 0.05
    assert next(x for x in default_assertions(0.99) if x.name == nr.name).max_rate == 0.99


def test_build_detector_is_detector(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    conn.execute("INSERT INTO orders SELECT * FROM orders LIMIT 1")
    det = build_assertion_detector(default_assertions())
    assert det.name == "assertion_catalog"
    assert "duplicate" in [x.type for x in det.detect(DuckDBAdapter(conn), {})]
