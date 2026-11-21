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
