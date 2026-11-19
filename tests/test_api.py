import sqlite3

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from dataquality_agent.agents.graph import build_graph
from dataquality_agent.agents.hitl import make_approve_node
from dataquality_agent.api.main import create_app
from dataquality_agent.api.runtime import PatrolRuntime, RunStore
from dataquality_agent.models import Anomaly, Diagnosis, Remediation, Report


def _mock_graph(high_risk=True, checkpointer=None):
    def inspect(state):
        return {"anomalies": [Anomaly(type="orphan", table="order_items")]}

    def diagnose(state):
        return {"diagnoses": [Diagnosis(root_cause_category="上游任务失败", confidence=0.9)]}

    def remediate(state):
        risk = "high" if high_risk else "low"
        return {"remediations": [Remediation(action_type="fix_sql", sql_or_suggestion="DELETE", risk_level=risk)]}

    def report(state):
        return {"report": Report(summary="done")}

    return build_graph(inspect, diagnose, remediate, make_approve_node(), report,
                       checkpointer=checkpointer or MemorySaver())


def _persistent_graph(checkpoint_path):
    return _mock_graph(high_risk=True, checkpointer=SqliteSaver(sqlite3.connect(checkpoint_path, check_same_thread=False)))


def test_patrol_awaiting_approval_and_resume():
    runtime = PatrolRuntime(_mock_graph(high_risk=True))
    client = TestClient(create_app(runtime))

    # 触发巡检 → 高危 → 停在审批
    resp = client.post("/patrol")
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    assert resp.json()["status"] == "awaiting_approval"

    # 审批通过 → 恢复 → 完成
    resp = client.post(f"/patrol/{run_id}/approve", json={"decision": {"0": "approved"}})
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    # 查询结果
    resp = client.get(f"/patrol/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert resp.json()["state"]["report"]["summary"] == "done"


def test_patrol_completes_without_approval():
    runtime = PatrolRuntime(_mock_graph(high_risk=False))
    client = TestClient(create_app(runtime))
    resp = client.post("/patrol")
    assert resp.json()["status"] == "completed"


def test_patrol_unknown_run_id_404():
    client = TestClient(create_app(PatrolRuntime(_mock_graph())))
    resp = client.get("/patrol/nonexistent")
    assert resp.status_code == 404


def test_static_frontend_served(tmp_path):
    (tmp_path / "index.html").write_text("<html>dashboard</html>", encoding="utf-8")
    client = TestClient(create_app(PatrolRuntime(_mock_graph()), static_dir=str(tmp_path)))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "dashboard" in resp.text


def test_restart_recovery(tmp_path):
    """进程重启后（同一 checkpoint 文件 + RunStore），list_runs 仍能列出、approve 仍能恢复。"""
    cp = str(tmp_path / "cp.sqlite")
    store = str(tmp_path / "runs.sqlite")

    r1 = PatrolRuntime(_persistent_graph(cp), RunStore(store))
    r1.trigger("abc")

    # 模拟重启：新 runtime 实例，同一 checkpoint + RunStore 文件
    r2 = PatrolRuntime(_persistent_graph(cp), RunStore(store))
    assert "abc" in r2.list_runs()
    r2.approve("abc", {"0": "approved"})
    assert r2.get("abc")["status"] == "completed"


def test_runstore_empty(tmp_path):
    """空 RunStore（Review Focus #3）：list_ids 为空、load 未知 run 返回 None。"""
    store = RunStore(str(tmp_path / "runs.sqlite"))
    assert store.list_ids() == []
    assert store.load("nope") is None
