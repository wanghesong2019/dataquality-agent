"""test_inspect.py —— 巡检节点的单元测试流程说明。

本测试不启动整张图，而是手动直接调节点，模拟 LangGraph 引擎的行为（引擎也就是
"拿当前 state 调这个函数"），从而在不需要 LLM、不跑整图的情况下单独验证巡检节点。

测试流程：
    inj = Injector(mini_warehouse)                    # ① 造注入器
    conn = inj.connect()                              # ② 拿 DuckDB 连接
    inj.run(conn, [{"type": "duplicate", ...}])       # ③ 注入"主键重复"异常（制造脏数据）
    node = make_inspect_node(DuckDBAdapter(conn))                    # ④ 造出巡检节点（重点句 1）
    result = node({"run_id": "r1"})                   # ⑤ 调用节点（重点句 2）
    assert "duplicate" in [a.type for a in result["anomalies"]]  # ⑥ 断言检出重复异常

重点句 1：node = make_inspect_node(DuckDBAdapter(conn))
    只造函数、不执行检测。make_inspect_node(conn) 是工厂，调用它返回里面的 inspect 函数
    （不是执行 inspect 函数体），返回的 inspect 被赋给 node，并通过闭包把 conn "打包"进去。
    此刻 node == inspect 函数，node 里已藏着 conn，但检测还没跑。

重点句 2：result = node({"run_id": "r1"})
    这才是真正执行。node(...) 就是 inspect(state)，把 {"run_id":"r1"} 当 state 传进去；
    函数体执行 run_detection(conn)（用闭包里的 conn）→ 得到 report → return {"anomalies": ...}。
    result 就是这个返回值，result["anomalies"] 即异常列表。
"""
from dataquality_agent.adapters import DuckDBAdapter
from dataquality_agent.agents.inspect import make_inspect_node
from dataquality_agent.data.injector import Injector


def test_inspect_node_detects_anomaly(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    inj.run(conn, [{"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 1}])
    node = make_inspect_node(DuckDBAdapter(conn))
    result = node({"run_id": "r1"})
    assert "duplicate" in [a.type for a in result["anomalies"]]
