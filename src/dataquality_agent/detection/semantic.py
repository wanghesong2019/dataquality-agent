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

# 数据字典：字段含义 + 合法取值域（材料来自 warehouse.py 的字段注释，结构化成 dict 喂给 LLM）
TABLE_CODECS = {
    "dwd_orders": {
        "order_id": {"meaning": "订单ID（主键）"},
        "customer_id": {"meaning": "客户ID"},
        "order_status": {"meaning": "订单状态",
                         "valid": "created/approved/invoiced/processing/shipped/delivered/canceled/unavailable"},
        "order_purchase_timestamp": {"meaning": "下单时间"},
        "order_approved_at": {"meaning": "支付批准时间（应 >= 下单时间）"},
        "order_delivered_carrier_date": {"meaning": "交付承运商时间"},
        "order_delivered_customer_date": {"meaning": "送达客户时间（delivered 订单必填）"},
        "order_estimated_delivery_date": {"meaning": "预计送达日期"},
    },
    "dwd_order_items": {
        "order_id": {"meaning": "订单ID（外键 → orders）"},
        "order_item_id": {"meaning": "订单内序号"},
        "product_id": {"meaning": "商品ID（外键 → products）"},
        "seller_id": {"meaning": "卖家ID（外键 → sellers）"},
        "shipping_limit_date": {"meaning": "卖家最晚发货期限（应 >= 下单时间）"},
        "price": {"meaning": "价格（应 >= 0）"},
        "freight_value": {"meaning": "运费（应 >= 0）"},
    },
}


def _parse_findings(resp: dict) -> list[dict]:
    """从 assistant 的 tool_calls 里取 submit_semantic_findings 的实参；解析失败降级空列表。

    为什么读 `call["function"]["arguments"]` 而不是 schema 里的键：发给模型的 tools 是
    SUBMIT_FINDINGS_SCHEMA，里面是 `parameters`（描述「参数应该长什么样」的 JSON Schema）；
    模型真调工具时，响应 tool_calls 里的 `function.arguments` 是它按 parameters 填出来的
    **实参 JSON 字符串**（如 '{"findings": [...]}'）。arguments 是「响应格式」的字段，不是
    schema 里的键——两者在 API 的两侧：schema 是发给模型的约束，arguments 是模型回传的实参。
    所以 json.loads(arguments) 拿到实参 dict，再取 findings。
    """
    for call in resp.get("tool_calls", []):
        if call.get("function", {}).get("name") == "submit_semantic_findings":
            try:
                return json.loads(call["function"]["arguments"]).get("findings", [])
            except json.JSONDecodeError:
                return []
    return []


def _column_profile(conn, table: str, cols: list[tuple[str, str]]) -> dict:
    """固定大小的列画像：cardinality / null 率 / min-max / 示例值。

    每列只有固定几个数字 + 最多 5 个随机示例值，token 成本不随行数增长（替代「取前 N 行」的原始行采样）。
    cardinality/null 率/min-max 是全表聚合（非采样）；示例值是随机 5 个 distinct 值
    （ORDER BY random()，不是前 5 个，避免偏向最早数据）。
    """
    profile: dict = {}
    for col_name, col_type in cols:
        row = conn.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT {col_name}), COUNT(*) - COUNT({col_name}), "
            f"MIN({col_name}), MAX({col_name}) FROM {table}"
        ).fetchone()
        total, cardinality, null_cnt, min_v, max_v = row
        exemplars = [r[0] for r in conn.execute(
            f"SELECT DISTINCT {col_name} FROM {table} ORDER BY random() LIMIT 5"
        ).fetchall()]
        profile[col_name] = {
            "type": col_type,
            "cardinality": cardinality,
            "null_rate": round(null_cnt / total, 4) if total else 0.0,
            "min": min_v,
            "max": max_v,
            "exemplars": exemplars,
        }
    return profile


def run_semantic_checks(conn, model=None) -> list[Anomaly]:
    """对每张 DWD 表做列画像 + 数据字典，让 LLM 找语义异常。

    model 缺省（None）时跳过——L2 是兜底层、非必需；eval 不传 model 时干净数据不报。
    """
    if model is None:
        return []
    anomalies: list[Anomaly] = []
    for table in ("dwd_orders", "dwd_order_items"):
        cols = conn.execute(f"DESCRIBE {table}").fetchall()
        profile = _column_profile(conn, table, [(c[0], c[1]) for c in cols])
        codec = TABLE_CODECS.get(table, {})
        prompt = (
            "你是数据质量语义审核员。下面是表的「数据字典」（字段含义 + 合法取值域）和「列画像」"
            "（cardinality/null 率/min-max/示例值），请找出语义异常"
            "（日期顺序颠倒、枚举值可疑、字段语义与名称/取值域不符、明显逻辑不一致）。"
            "没有就返回空 findings 列表。\n"
            f"表：{table}\n数据字典：{codec}\n列画像：{profile}\n"
            "Fail if：枚举值不在合法取值域内；delivered 订单缺送达日期；"
            "时间字段顺序颠倒（如送达/批准早于下单）；price/freight_value 为负。"
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
