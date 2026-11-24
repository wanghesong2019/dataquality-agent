"""L2 LLM 语义检测：让 LLM 找规则/统计抓不到的语义异常（兜底层，可选）。

给 LLM 喂「数据字典」（字段含义 + 合法取值域）+「列画像」（cardinality / null 率 / min-max / 示例值）
而非原始行——列画像是固定大小的，token 成本不随行数增长（业界主流做法）。
"""
import json

from dataquality_agent.models import Anomaly

# 语义发现的 function calling schema：让 LLM 只能输出结构化 findings 列表（L2 强制）
SUBMIT_FINDINGS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_semantic_findings",
        "description": "Submit the semantic anomalies found for this table (empty list if none)",
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

# 数据字典：字段含义 + 合法取值域（材料来自 warehouse.py 的字段注释，结构化成 dict 喂给 LLM）
TABLE_CODECS = {
    "dwd_orders": {
        "order_id": {"meaning": "order ID (primary key)"},
        "customer_id": {"meaning": "customer ID"},
        "order_status": {"meaning": "order status",
                         "valid": "created/approved/invoiced/processing/shipped/delivered/canceled/unavailable"},
        "order_purchase_timestamp": {"meaning": "purchase time"},
        "order_approved_at": {"meaning": "payment approval time (should be >= purchase time)"},
        "order_delivered_carrier_date": {"meaning": "carrier handoff time"},
        "order_delivered_customer_date": {"meaning": "delivery time to customer (required for delivered orders)"},
        "order_estimated_delivery_date": {"meaning": "estimated delivery date"},
    },
    "dwd_order_items": {
        "order_id": {"meaning": "order ID (foreign key → orders)"},
        "order_item_id": {"meaning": "order item sequence number"},
        "product_id": {"meaning": "product ID (foreign key → products)"},
        "seller_id": {"meaning": "seller ID (foreign key → sellers)"},
        "shipping_limit_date": {"meaning": "seller latest shipping deadline (should be >= purchase time)"},
        "price": {"meaning": "price (should be >= 0)"},
        "freight_value": {"meaning": "freight value (should be >= 0)"},
    },
}


def _parse_findings(resp: dict) -> list[dict]:
    """从 assistant 的 tool_calls 里取 submit_semantic_findings 的实参；解析失败降级空列表。"""
    for call in resp.get("tool_calls", []):
        if call.get("function", {}).get("name") == "submit_semantic_findings":
            try:
                return json.loads(call["function"]["arguments"]).get("findings", [])
            except json.JSONDecodeError:
                return []
    return []


def _column_profile(adapter, table: str, cols: list[tuple[str, str]]) -> dict:
    """固定大小的列画像：cardinality / null 率 / min-max / 示例值。

    每列只有固定几个数字 + 最多 5 个随机示例值，token 成本不随行数增长。
    """
    profile: dict = {}
    for col_name, col_type in cols:
        row = adapter.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT {col_name}), COUNT(*) - COUNT({col_name}), "
            f"MIN({col_name}), MAX({col_name}) FROM {table}"
        )[0]
        total, cardinality, null_cnt, min_v, max_v = row
        exemplars = [r[0] for r in adapter.execute(
            f"SELECT DISTINCT {col_name} FROM {table} ORDER BY random() LIMIT 5"
        )]
        profile[col_name] = {
            "type": col_type,
            "cardinality": cardinality,
            "null_rate": round(null_cnt / total, 4) if total else 0.0,
            "min": min_v,
            "max": max_v,
            "exemplars": exemplars,
        }
    return profile


def run_semantic_checks(adapter, model=None) -> list[Anomaly]:
    """对每张 DWD 表做列画像 + 数据字典，让 LLM 找语义异常。

    model 缺省（None）时跳过——L2 是兜底层、非必需；eval 不传 model 时干净数据不报。
    """
    if model is None:
        return []
    anomalies: list[Anomaly] = []
    for table in ("dwd_orders", "dwd_order_items"):
        cols = list(adapter.describe_table(table).items())
        profile = _column_profile(adapter, table, cols)
        codec = TABLE_CODECS.get(table, {})
        prompt = (
            "You are a data quality semantic auditor. Below is the table's data dictionary (field meaning + valid "
            "value domain) and column profile"
            "(cardinality/null rate/min-max/exemplars); find semantic anomalies"
            "(date ordering inverted, suspicious enum values, field semantics inconsistent with name/domain, obvious "
            "logical inconsistency)."
            "If none, return an empty findings list.\n"
            f"Table: {table}\nData dictionary: {codec}\nColumn profile: {profile}\n"
            "Fail if: enum value outside the valid domain; delivered order missing delivery date;"
            "time fields inverted (e.g. delivery/approval before purchase); price/freight_value negative."
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
