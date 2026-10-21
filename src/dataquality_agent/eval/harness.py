"""评估编排核心：复检 apply + 可逆/数据丢失分型 + EvalReport 组装。"""
from dataquality_agent.detection.runner import run_detection
from dataquality_agent.eval.metrics import (
    EvalReport,
    attribution_accuracy,
    classify_failures,
    end_to_end_success,
    evaluate_detection,
    evaluate_detection_by_type,
    remediation_success,
    total_latency,
)
from dataquality_agent.eval.trajectory import evaluate_trajectories

# 可逆 = SQL 可复原；数据丢失 = 原始值已毁、需上游重跑（复检口径分型的关键）
REVERSIBLE_TYPES = {"duplicate", "value_range"}


def classify_reversibility(anomaly_type: str) -> str:
    """把异常类型分成「可逆」（SQL 可复原）vs「数据丢失」（需上游重跑）。"""
    return "可逆" if anomaly_type in REVERSIBLE_TYPES else "数据丢失"


def apply_remediation(conn, remediation) -> bool:
    """在一次性 eval DB 上执行 fix_sql（best-effort），返回是否成功执行。

    只执行 action_type == "fix_sql" 且非空的 SQL；去掉 -- 注释行（模型常带说明注释）；
    执行失败（语法错/非 SQL/只剩注释）返回 False。
    """
    sql = (remediation.sql_or_suggestion or "").strip()
    if remediation.action_type != "fix_sql" or not sql:
        return False
    statements = [line for line in sql.splitlines() if line.strip() and not line.strip().startswith("--")]
    sql = "\n".join(statements).strip()
    if not sql:
        return False
    try:
        conn.execute(sql)
        return True
    except Exception:
        return False


def remediate_and_recheck(conn, remediations, current_date=None, expected_schema=None) -> list:
    """应用 fix_sql 整改 → 重跑检测，返回修复后的异常列表（复检口径）。

    current_date / expected_schema 透传给 run_detection，保证复检和初检用同一基线。
    """
    for r in remediations:
        apply_remediation(conn, r)
    return run_detection(conn, current_date=current_date, expected_schema=expected_schema).anomalies


def remediation_success_by_reversibility(detected_before, detected_after, injected) -> dict:
    """按「可逆 / 数据丢失」分型算整改成功率（不粉饰数字）。"""
    groups: dict[str, list] = {"可逆": [], "数据丢失": []}
    for i in injected:
        groups[classify_reversibility(i.type)].append(i)
    result = {}
    for label, group in groups.items():
        if group:
            result[label] = remediation_success(detected_before, detected_after, group)
    return result


def run_eval(injected, detected_before, diagnoses, detected_after, stats, cost_ledger,
             llm_seconds: float = 0.0, baseline=None) -> EvalReport:
    """组装 EvalReport：把各阶段输出喂给 metrics 函数，得到面试可报的量化数字。

    llm_seconds = 归因/整改等 LLM 调用耗时（检测层耗时在 stats 里，两者相加 = 全流程耗时）。
    baseline = 干净基线异常（真实数据自带问题），透传给检测指标从误报里扣除。
    """
    return EvalReport(
        detection=evaluate_detection(detected_before, injected, baseline),
        detection_by_type=evaluate_detection_by_type(detected_before, injected, baseline),
        attribution_accuracy=attribution_accuracy(detected_before, diagnoses, injected),
        remediation_success=remediation_success(detected_before, detected_after, injected),
        end_to_end_success=end_to_end_success(detected_before, diagnoses, detected_after, injected),
        latency_seconds=(total_latency(stats) if stats else 0.0) + llm_seconds,
        total_tokens=cost_ledger.total_tokens if cost_ledger else 0,
        total_cost=cost_ledger.total_cost if cost_ledger else 0.0,
        llm_calls=cost_ledger.llm_calls if cost_ledger else 0,
        trajectory=evaluate_trajectories(diagnoses),
        failure_taxonomy=classify_failures(detected_before, diagnoses, detected_after, injected),
    )
