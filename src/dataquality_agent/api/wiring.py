"""生产运行时装配：把数据层/模型/工具/图接起来，返回 PatrolRuntime。"""
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from dataquality_agent.agents.diagnose import make_diagnose_node
from dataquality_agent.agents.graph import build_graph
from dataquality_agent.agents.hitl import make_approve_node
from dataquality_agent.agents.inspect import make_inspect_node
from dataquality_agent.agents.remediate import make_remediate_node
from dataquality_agent.agents.report import make_report_node
from dataquality_agent.agents.tooling import build_diagnose_tools
from dataquality_agent.api.runtime import PatrolRuntime
from dataquality_agent.config import Settings
from dataquality_agent.data.lineage import Lineage
from dataquality_agent.data.warehouse import Warehouse
from dataquality_agent.llm import DeepSeekClient, LLMAdapter
from dataquality_agent.observability.tracing import Tracer
from dataquality_agent.rag.cases import build_retriever


def build_runtime(settings: Settings | None = None) -> PatrolRuntime:
    """装配完整巡检图（巡检→归因→整改→审批→报告），返回 PatrolRuntime。

    模型走 DeepSeek function calling；HITL 用 SqliteSaver（SQLite 持久化，审批状态跨进程重启不丢，生产可换 Postgres）。
    """
    settings = settings or Settings()
    warehouse = Warehouse(settings)
    warehouse.build()
    conn = warehouse.connect()

    adapter = LLMAdapter(DeepSeekClient(), tracer=Tracer())
    tools = build_diagnose_tools(conn, Lineage(), build_retriever())

    # HITL 持久化：审批暂停/恢复的状态落盘 SQLite，进程重启不丢（生产可换 Postgres）
    Path(settings.checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    checkpointer = SqliteSaver(sqlite3.connect(settings.checkpoint_path, check_same_thread=False))

    graph = build_graph(
        make_inspect_node(conn),
        make_diagnose_node(adapter, tools),
        make_remediate_node(adapter, conn),
        make_approve_node(),
        make_report_node(adapter),
        checkpointer=checkpointer,
    )
    return PatrolRuntime(graph)
