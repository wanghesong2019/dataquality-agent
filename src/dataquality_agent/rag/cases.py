"""历史案例库：喂给归因 Agent 的 cases 工具（混合检索）。

案例来源 = 注入异常回填（§12 P3 第一块拼图）：把可注入的 10 类异常（含 ground-truth 根因类别）
沉淀成案例库，替代手写 demo。每类一条 (type, table, column, 异常描述, 根因类别, 整改)。
根因类别对齐 injector.py 的 ROOT_CAUSE_CATEGORY。
"""
import json
from pathlib import Path

from dataquality_agent.rag.embedder import build_embedder
from dataquality_agent.rag.retriever import Retriever
from dataquality_agent.rag.tokenizer import tokenize

# 注入异常 → 案例回填：10 类可注入异常，含 ground-truth 根因
INJECTION_CASES = [
    ("duplicate", "orders", "order_id", "主键重复", "脏数据注入", "去重 DELETE"),
    ("orphan", "order_items", "product_id", "孤儿外键（父表行被删）", "上游任务失败", "重跑上游加载"),
    ("null_rate", "orders", "order_delivered_customer_date", "delivered 订单交付日期为 null", "脏数据注入", "回填日期"),
    ("value_range", "order_items", "price", "价格出现负值", "脏数据注入", "回填正确价格"),
    ("lineage_break", "daily_metrics", "order_date", "下游表停更（水位线落后上游）", "上游数据延迟", "补跑上游任务"),
    ("freshness", "orders", "order_purchase_timestamp", "数据停更（最新分区落后当前日期）", "上游数据延迟", "补跑采集"),
    ("schema_drift", "dwd_orders", "order_approved_at", "列缺失/类型变更", "schema变更", "回滚 schema"),
    ("amount_mismatch", "orders", "payment_total", "支付总额与明细总额不一致", "脏数据注入", "对齐金额"),
    ("state_conflict", "orders", "order_status", "已取消订单却有评价", "脏数据注入", "清理矛盾状态"),
    ("zip_inconsistency", "geolocation", "geolocation_zip_code_prefix", "同一邮编映射多个城市", "脏数据注入", "修正邮编映射"),
]


FLYWHEEL_CASES_PATH = Path(__file__).resolve().parents[3] / "data" / "flywheel_cases.json"


def load_flywheel_cases(path: Path = FLYWHEEL_CASES_PATH) -> list[dict]:
    """读数据飞轮回流的历史案例（eval 结果沉淀）。不存在则空。"""
    if Path(path).exists():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return []


def persist_flywheel_cases(cases: list[dict], path: Path = FLYWHEEL_CASES_PATH) -> None:
    """把 eval 结果回流成案例，落盘 JSON（数据飞轮的写入侧）。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_cases() -> list[dict]:
    """案例库 = 静态注入案例 + 数据飞轮回流案例（同 id 用飞轮更新版覆盖）。"""
    static = [
        {"id": f"{typ}_{table}", "text": f"{table} {column} {desc}，根因{category}，整改{remedy}"}
        for typ, table, column, desc, category, remedy in INJECTION_CASES
    ]
    merged = {c["id"]: c for c in static}
    for c in load_flywheel_cases():
        merged[c["id"]] = c
    return list(merged.values())


CASES = _build_cases()

# 有标注的检索测试集：query = 归因 Agent 用 cases 工具时的自然语言查询，relevant = 应命中的 case id
QUERIES = [
    {"query": "orders 主键重复", "relevant": "duplicate_orders"},
    {"query": "order_items 孤儿外键", "relevant": "orphan_order_items"},
    {"query": "delivered 交付日期 null", "relevant": "null_rate_orders"},
    {"query": "order_items 价格负值", "relevant": "value_range_order_items"},
    {"query": "下游表停更", "relevant": "lineage_break_daily_metrics"},
    {"query": "数据停更 分区落后", "relevant": "freshness_orders"},
    {"query": "列缺失 类型变更", "relevant": "schema_drift_dwd_orders"},
    {"query": "支付总额 明细不一致", "relevant": "amount_mismatch_orders"},
    {"query": "已取消订单有评价", "relevant": "state_conflict_orders"},
    {"query": "邮编映射多个城市", "relevant": "zip_inconsistency_geolocation"},
]


def build_retriever() -> Retriever:
    """案例检索器：配了 EMBEDDING_* 用 OpenAIEmbedder(BGE-M3)，否则词袋 fallback。"""
    vocab = sorted({w for c in CASES for w in tokenize(c["text"])})
    r = Retriever(build_embedder(vocab))
    r.index(CASES)
    return r
