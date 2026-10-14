from dataquality_agent.agents.tooling import build_diagnose_tools
from dataquality_agent.data.injector import Injector
from dataquality_agent.data.lineage import Lineage
from dataquality_agent.rag.embedder import BagOfWordsEmbedder
from dataquality_agent.rag.retriever import Retriever


def test_build_diagnose_tools(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    retriever = Retriever(BagOfWordsEmbedder(["订单"]))
    retriever.index([{"id": "c1", "text": "订单 主键 重复"}])

    tools = build_diagnose_tools(conn, Lineage(), retriever)
    assert {t.name for t in tools} == {"schema", "lineage", "cases", "sql"}

    schema = next(t for t in tools if t.name == "schema")
    assert "order_id" in schema.func({"table": "orders"})  # 能查到列名

    lineage = next(t for t in tools if t.name == "lineage")
    assert "orders" in lineage.func({"table": "order_items"})  # order_items 上游含 orders

    cases = next(t for t in tools if t.name == "cases")
    assert "c1" in cases.func({"query": "订单 重复"})  # 能检索到相似案例

    sql_tool = next(t for t in tools if t.name == "sql")
    assert "3" in sql_tool.func({"sql": "SELECT COUNT(*) FROM orders"})  # mini 数仓 3 单
