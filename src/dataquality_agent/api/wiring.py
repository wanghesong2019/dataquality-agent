"""生产运行时装配：把数据层/模型/工具/图接起来，返回 PatrolRuntime。"""
import os
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from dataquality_agent.adapters import DuckDBAdapter
from dataquality_agent.agents.diagnose import make_thin_diagnose_node
from dataquality_agent.agents.graph import build_graph
from dataquality_agent.agents.hitl import make_approve_node
from dataquality_agent.agents.inspect import make_inspect_node
from dataquality_agent.agents.remediate import make_remediate_node
from dataquality_agent.agents.report import make_report_node
from dataquality_agent.api.runtime import PatrolRuntime, RunStore
from dataquality_agent.config import Settings
from dataquality_agent.data.lineage import Lineage
from dataquality_agent.data.warehouse import Warehouse
from dataquality_agent.llm import DeepSeekClient, LLMAdapter
from dataquality_agent.observability.tracing import LangfuseBackend, Tracer
from dataquality_agent.rag.cases import build_retriever


def _build_tracer_backend() -> LangfuseBackend:
    """按 env 配 Langfuse 上报后端；未配 key 时内部惰性导入 + no-op（不拖主流程）。"""
    return LangfuseBackend(
        public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
        host=os.environ.get("LANGFUSE_HOST"),
    )


def build_runtime(settings: Settings | None = None) -> PatrolRuntime:
    """装配完整巡检图（巡检→薄归因→整改→审批→报告），返回 PatrolRuntime。

    归因走「确定性证据装配 + 单一 LLM 调用」的薄 Agent（证据一等）；模型走 DeepSeek function calling；
    HITL 用 SqliteSaver（SQLite 持久化，审批状态跨进程重启不丢，生产可换 Postgres）。
    """
    settings = settings or Settings()
    warehouse = Warehouse(settings)
    warehouse.build()
    conn = warehouse.connect()
    wh = DuckDBAdapter(conn)

    adapter = LLMAdapter(DeepSeekClient(), tracer=Tracer(backend=_build_tracer_backend()))
    retriever = build_retriever()

    # HITL 持久化：审批暂停/恢复的状态落盘 SQLite，进程重启不丢（生产可换 Postgres）
    Path(settings.checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    checkpointer = SqliteSaver(sqlite3.connect(settings.checkpoint_path, check_same_thread=False, timeout=30))

    graph = build_graph(
        make_inspect_node(wh, adapter),
        make_thin_diagnose_node(adapter, wh, Lineage(), retriever),
        make_remediate_node(adapter, wh),
        make_approve_node(tracer=adapter.tracer),
        make_report_node(adapter),
        checkpointer=checkpointer,
    )
    run_store = RunStore(str(Path(settings.checkpoint_path).with_name("runs.sqlite")))
    return PatrolRuntime(graph, run_store)
