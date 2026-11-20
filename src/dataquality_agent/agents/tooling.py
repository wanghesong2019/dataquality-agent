"""归因/专职 Agent 的工具构造（schema / lineage / cases / sql，全只读）。

§13 起把 4 个工具拆成 3 组，供专职 Agent 各自取用：
- 血缘归因 = lineage
- SQL 排查 = schema + sql
- 案例检索 = cases
`build_diagnose_tools` 保留，把 4 个工具合一（兼容单图版 diagnose）。
"""
from dataquality_agent.prompts import Tool
from dataquality_agent.tools.sql import SafeSQL


def build_schema_tool(adapter) -> Tool:
    """schema 工具：查某张表的列名与类型（DESCRIBE）。"""
    return Tool(name="schema", description="查某张表的列名与类型（DESCRIBE），写 SQL 前先查 schema 确认列名",
                parameters={"type": "object", "properties": {"table": {"type": "string"}}, "required": ["table"]},
                func=lambda args: str(adapter.describe_table(args["table"])))


def build_lineage_tool(lineage) -> Tool:
    """lineage 工具：查某张表的上游血缘。"""
    return Tool(name="lineage", description="查某张表的上游血缘（它依赖哪些上游表）",
                parameters={"type": "object", "properties": {"table": {"type": "string"}}, "required": ["table"]},
                func=lambda args: str(lineage.upstream(args["table"])))


def build_sql_tool(adapter, sql_whitelist=None) -> Tool:
    """sql 工具：执行只读诊断 SQL（仅 SELECT），护栏走 SafeSQL。"""
    whitelist = sql_whitelist or set(adapter.list_tables())
    safe_sql = SafeSQL(adapter, whitelist)
    return Tool(name="sql", description="执行只读诊断 SQL（仅 SELECT）",
                parameters={"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
                func=lambda args: str(safe_sql.run(args["sql"])))


def build_cases_tool(retriever, tracer=None) -> Tool:
    """cases 工具：在历史案例库检索相似案例；命中 ID 累积在 tool.matched_case_ids（防模型自述幻觉）。"""
    matched_case_ids: list[str] = []

    def cases_func(args: dict) -> str:
        if tracer is not None:
            with tracer.span("retrieve", input=args["query"]):
                results = retriever.search(args["query"], k=3)
        else:
            results = retriever.search(args["query"], k=3)
        for r in results:
            if r["id"] not in matched_case_ids:
                matched_case_ids.append(r["id"])
        return str(results)

    cases_tool = Tool(name="cases", description="在历史案例库检索相似异常案例（返回案例根因+整改）",
                      parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                      func=cases_func)
    cases_tool.matched_case_ids = matched_case_ids
    return cases_tool


def build_lineage_tools(lineage) -> list[Tool]:
    """血缘归因专职 Agent 的工具集。"""
    return [build_lineage_tool(lineage)]


def build_sql_tools(adapter, sql_whitelist=None) -> list[Tool]:
    """SQL 排查专职 Agent 的工具集（schema + sql）。"""
    return [build_schema_tool(adapter), build_sql_tool(adapter, sql_whitelist)]


def build_cases_tools(retriever, tracer=None) -> list[Tool]:
    """案例检索专职 Agent 的工具集。"""
    return [build_cases_tool(retriever, tracer)]


def build_diagnose_tools(adapter, lineage, retriever, sql_whitelist=None, tracer=None) -> list[Tool]:
    """构造归因 Agent 的 4 工具合一：schema / lineage / cases / sql（只读）。

    sql 的只读护栏走 SafeSQL；表白名单缺省 = 当前数仓的全部表（从 adapter.list_tables() 派生）。
    tracer 用于给 cases 里的 RAG 检索埋 span（步骤级 Trace）。
    """
    return [
        build_schema_tool(adapter),
        build_lineage_tool(lineage),
        build_cases_tool(retriever, tracer),
        build_sql_tool(adapter, sql_whitelist),
    ]
