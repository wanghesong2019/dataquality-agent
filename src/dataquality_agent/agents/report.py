"""报告 Agent：汇总巡检结果。"""
from dataquality_agent.models import Report
from dataquality_agent.prompts import build_report_prompt


def make_report_node(model):
    """返回报告节点函数。model 通过闭包注入。"""
    def report(state):
        n_anomalies = len(state.get("anomalies", []))
        n_remediations = len(state.get("remediations", []))
        summary = model(build_report_prompt(n_anomalies, n_remediations))
        return {"report": Report(
            summary=summary, anomaly_count=n_anomalies, remediation_count=n_remediations,
        )}
    return report
