"""巡检 Agent（Planner + Executor）：调 M1 检测，产出结构化异常清单。"""
from dataquality_agent.detection.runner import run_detection


def make_inspect_node(conn):
    """返回巡检节点函数。conn 通过闭包注入（不放进 state——state 需可序列化）。"""
    def inspect(state):
        report = run_detection(conn)
        return {"anomalies": report.anomalies}
    return inspect
