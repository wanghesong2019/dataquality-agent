"""飞轮案例写入侧：id 唯一化 + 文本补 desc/remedy（4.1 的 2 个 bug 修复）。"""
from dataquality_agent.data.injector import InjectedAnomaly
from dataquality_agent.rag.cases import CASE_REMEDY, make_flywheel_case


def _inj(type_: str, table: str, column: str | None) -> InjectedAnomaly:
    return InjectedAnomaly(
        type=type_, table=table, column=column,
        root_cause=f"test {type_}",
        root_cause_category="脏数据注入",
        location="test",
    )


def test_flywheel_id_unique_per_column():
    """同 type 同表不同列 → id 唯一（修复 orphan_order_items / null_rate_orders 冲突）。"""
    a = make_flywheel_case(_inj("orphan", "order_items", "product_id"))
    b = make_flywheel_case(_inj("orphan", "order_items", "seller_id"))
    assert a["id"] == "orphan_order_items_product_id"
    assert b["id"] == "orphan_order_items_seller_id"
    assert a["id"] != b["id"]


def test_flywheel_id_sanitizes_column():
    """复合键 join 出的逗号 → 下划线。"""
    c = make_flywheel_case(_inj("duplicate", "payments", "order_id,payment_sequential"))
    assert c["id"] == "duplicate_payments_order_id_payment_sequential"


def test_flywheel_id_fallback_without_column():
    """column 缺省 → 退化为 type_table。"""
    c = make_flywheel_case(_inj("duplicate", "orders", None))
    assert c["id"] == "duplicate_orders"


def test_flywheel_text_has_desc_and_remedy():
    """文本不再贫瘠：含 desc + 根因类别 + 整改动作。"""
    c = make_flywheel_case(_inj("duplicate", "orders", "order_id"))
    assert "主键/唯一键重复" in c["text"]
    assert "根因脏数据注入" in c["text"]
    assert "整改去重 DELETE" in c["text"]


def test_flywheel_case_metadata():
    c = make_flywheel_case(_inj("value_range", "order_items", "price"))
    assert c["type"] == "value_range"
    assert c["root_cause"] == "脏数据注入"
    assert c["id"] == "value_range_order_items_price"
    assert c["table"] == "order_items"
    assert c["column"] == "price"


def test_case_remedy_covers_all_injectable_types():
    """每个可注入类型都有 desc/remedy 映射（含 Tier 3/4 新增）。"""
    for t in ["duplicate", "orphan", "null_rate", "value_range", "lineage_break",
              "freshness", "schema_drift", "time_inversion", "future_date",
              "volume", "distribution"]:
        assert t in CASE_REMEDY, f"缺 {t} 的 desc/remedy"
