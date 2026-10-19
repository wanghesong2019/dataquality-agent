"""L2 LLM 语义检测：让 LLM 找规则/统计抓不到的语义异常（兜底层，可选）。"""
import json

from dataquality_agent.models import Anomaly

# 语义发现的 function calling schema：让 LLM 只能输出结构化 findings 列表（L2 强制）
SUBMIT_FINDINGS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_semantic_findings",
        "description": "提交这张表发现的语义异常（没有则为空列表）",
        "parameters": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "evidence": {"type": "string"},
                        },
                        "required": ["column", "evidence"],
                    },
                },
            },
            "required": ["findings"],
        },
    },
}


def _parse_findings(resp: dict) -> list[dict]:
    """从 assistant message 取 submit_semantic_findings 参数；解析失败降级空列表。"""
    for call in resp.get("tool_calls", []):
        if call.get("function", {}).get("name") == "submit_semantic_findings":
            try:
                return json.loads(call["function"]["arguments"]).get("findings", [])
            except json.JSONDecodeError:
                return []
    return []


def run_semantic_checks(conn, model=None) -> list[Anomaly]:
    """对每张 DWD 表采样，让 LLM 找语义异常（日期顺序颠倒、枚举可疑、字段语义不符等）。

    model 缺省（None）时跳过——L2 是兜底层、非必需；eval 不传 model 时干净数据不报。
    """
    if model is None:
        return []
    anomalies: list[Anomaly] = []
    for table in ("dwd_orders", "dwd_order_items"):
        cols = conn.execute(f"DESCRIBE {table}").fetchall()
        rows = conn.execute(f"SELECT * FROM {table} LIMIT 3").fetchall()
        if not rows:
            continue
        schema = {c[0]: c[1] for c in cols}
        prompt = (
            "你是数据质量语义审核员。下面是表 schema 和采样数据，请找出语义异常"
            "（如日期顺序颠倒、枚举值可疑、字段语义与名称不符、明显逻辑不一致）。"
            "没有就返回空 findings 列表。\n"
            f"表：{table}\nschema：{schema}\n采样行：{rows}"
        )
        resp = model.chat(
            [{"role": "user", "content": prompt}],
            tools=[SUBMIT_FINDINGS_SCHEMA],
            tool_choice={"type": "function", "function": {"name": "submit_semantic_findings"}},
        )
        for f in _parse_findings(resp):
            anomalies.append(Anomaly(
                type="semantic", table=table, column=f.get("column"),
                evidence=f.get("evidence", ""),
            ))
    return anomalies
