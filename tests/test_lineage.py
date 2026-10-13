from dataquality_agent.data.lineage import Lineage


def test_lineage_upstream():
    l = Lineage()
    assert l.upstream("order_items") == ["orders", "products", "sellers"]
    assert l.upstream("payments") == ["orders"]
    assert l.upstream("reviews") == ["orders"]
    assert l.upstream("daily_metrics") == ["orders", "order_items"]


def test_lineage_downstream():
    l = Lineage()
    assert sorted(l.downstream("orders")) == ["daily_metrics", "order_items", "payments", "reviews"]
    assert l.downstream("products") == ["order_items"]
    assert l.downstream("order_items") == ["daily_metrics"]


def test_lineage_edges():
    l = Lineage()
    edges = set(l.all_edges())
    assert ("orders", "order_items") in edges
    assert ("products", "order_items") in edges
    assert ("sellers", "order_items") in edges
    assert ("orders", "payments") in edges
    assert ("orders", "reviews") in edges
    assert ("orders", "daily_metrics") in edges
    assert ("order_items", "daily_metrics") in edges
