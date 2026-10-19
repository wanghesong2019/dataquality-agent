"""生产运行时装配：把数据层/模型/工具/图接起来，返回 PatrolRuntime。"""
from langgraph.checkpoint.memory import MemorySaver

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

    模型走 DeepSeek function calling；HITL 用 MemorySaver（demo 内存态，生产换持久化 checkpointer）。
    """
    settings = settings or Settings()
    warehouse = Warehouse(settings)
    warehouse.build()
    conn = warehouse.connect()

    adapter = LLMAdapter(DeepSeekClient(), tracer=Tracer())
    tools = build_diagnose_tools(conn, Lineage(), build_retriever())

    graph = build_graph(
        make_inspect_node(conn),
        make_diagnose_node(adapter, tools),
        make_remediate_node(adapter, conn),
        make_approve_node(),
        make_report_node(adapter),
        checkpointer=MemorySaver(),
    )
    return PatrolRuntime(graph)
