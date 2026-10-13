from dataquality_agent.agents.inspect import make_inspect_node
from dataquality_agent.data.injector import Injector


def test_inspect_node_detects_anomaly(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    inj.run(conn, [{"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 1}])
    node = make_inspect_node(conn)
    result = node({"run_id": "r1"})
    assert "duplicate" in [a.type for a in result["anomalies"]]
