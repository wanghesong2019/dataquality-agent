"""归因 Agent 的工具构造（lineage / cases / sql）。"""
from dataquality_agent.prompts import Tool
from dataquality_agent.tools.sql import SafeSQL


def build_diagnose_tools(conn, lineage, retriever, sql_whitelist=None) -> list[Tool]:
    """构造归因 Agent 的三个工具：lineage / cases / sql（只读）。

    sql 的只读护栏走 SafeSQL；表白名单缺省 = 当前数仓的全部表（从 SHOW TABLES 派生）。
    """
    whitelist = sql_whitelist or {t[0] for t in conn.execute("SHOW TABLES").fetchall()}
    safe_sql = SafeSQL(conn, whitelist)
    return [
        Tool(name="lineage", description="查某张表的上游血缘（它依赖哪些上游表）",
             parameters={"type": "object", "properties": {"table": {"type": "string"}}, "required": ["table"]},
             func=lambda args: str(lineage.upstream(args["table"]))),
        Tool(name="cases", description="在历史案例库检索相似异常案例（返回案例根因+整改）",
             parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
             func=lambda args: str(retriever.search(args["query"], k=3))),
        Tool(name="sql", description="执行只读诊断 SQL（仅 SELECT）",
             parameters={"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
             func=lambda args: str(safe_sql.run(args["sql"]))),
    ]
