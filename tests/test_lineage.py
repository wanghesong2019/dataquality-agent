from dataquality_agent.data.lineage import Lineage


def test_lineage_fk_upstream():
    """FK 依赖边保留：归因 Agent 追 orphan 根因时能往上溯源。"""
    l = Lineage()
    assert l.upstream("order_items") == ["orders", "products", "sellers"]
    assert l.upstream("payments") == ["orders"]
    assert l.upstream("reviews") == ["orders"]


def test_lineage_build_upstream():
    """构建血缘：DWD/DWS 的上游对齐 warehouse.py 真正 build 出来的表。"""
    l = Lineage()
    # ODS → DWD（类型规范化）
    assert l.upstream("dwd_orders") == ["orders"]
    assert l.upstream("dwd_payments") == ["payments"]
    assert l.upstream("dwd_reviews") == ["reviews"]
    # DWD/ODS → DWS（聚合）
    assert l.upstream("daily_metrics") == ["orders", "order_items"]
    assert l.upstream("seller_metrics") == ["order_items", "dwd_reviews"]
    assert l.upstream("category_metrics") == ["order_items", "products"]
    assert l.upstream("payment_summary") == ["dwd_payments"]


def test_lineage_ods_source_has_no_upstream():
    """ODS 源表无表级上游（直接从 CSV 落库），upstream 返回空。"""
    l = Lineage()
    assert l.upstream("orders") == []
    assert l.upstream("products") == []


def test_lineage_downstream():
    """downstream 覆盖 FK 依赖 + 构建血缘两类下游。"""
    l = Lineage()
    assert set(l.downstream("orders")) == {
        "daily_metrics", "dwd_orders", "order_items", "payments", "reviews",
    }
    assert set(l.downstream("order_items")) == {
        "daily_metrics", "dwd_order_items", "seller_metrics", "category_metrics",
    }
    assert l.downstream("dwd_reviews") == ["seller_metrics"]


def test_lineage_edges():
    """all_edges 含 FK 边 + 构建边。"""
    l = Lineage()
    edges = set(l.all_edges())
    # FK 边
    assert ("orders", "order_items") in edges
    assert ("products", "order_items") in edges
    # 构建边 ODS → DWD
    assert ("orders", "dwd_orders") in edges
    assert ("payments", "dwd_payments") in edges
    # 构建边 → DWS
    assert ("dwd_reviews", "seller_metrics") in edges
    assert ("dwd_payments", "payment_summary") in edges
