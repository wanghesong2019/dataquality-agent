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


# 飞轮案例写入侧的元数据：注入类型 → (中文异常描述, 整改动作)。
# 与静态 INJECTION_CASES 的 desc/remedy 同语义，根因类别对齐 injector.py 的 ROOT_CAUSE_CATEGORY。
CASE_REMEDY = {
    "duplicate": ("主键/唯一键重复", "去重 DELETE"),
    "orphan": ("孤儿外键（父表行被删）", "重跑上游加载"),
    "null_rate": ("关键列为 null", "回填缺失值"),
    "value_range": ("数值超出合法值域", "回填正确值"),
    "lineage_break": ("下游表停更（水位线落后上游）", "补跑上游任务"),
    "freshness": ("数据停更（最新分区落后当前日期）", "补跑采集"),
    "schema_drift": ("列缺失/类型变更", "回滚 schema"),
    "amount_mismatch": ("支付总额与明细总额不一致", "对齐金额"),
    "state_conflict": ("已取消订单却有评价", "清理矛盾状态"),
    "zip_inconsistency": ("同一邮编映射多个城市", "修正邮编映射"),
    "time_inversion": ("交付日期早于下单日期", "修正时间字段"),
    "future_date": ("时间戳超出采集范围", "修正时间戳"),
    "volume": ("日单量/指标突刺", "复查业务口径"),
    "distribution": ("分类分布漂移", "复查业务口径"),
}


def make_flywheel_case(inj) -> dict:
    """把一条注入异常（InjectedAnomaly）转成飞轮案例：id 唯一化 + 文本补 desc/remedy。

    id 规则 = `{type}_{table}_{column}`（column 里的非字母数字替换为 `_`；column 缺省退化为
    `{type}_{table}`）。消除「同 type 同表不同列」的 id 冲突（如 orphan_order_items 的
    products/sellers 两例、null_rate_orders 的 delivered 日期/customer_id 两例）。
    """
    desc, remedy = CASE_REMEDY.get(inj.type, ("异常", "人工核查"))
    column = (inj.column or "").strip()
    cid_col = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in column)
    cid = f"{inj.type}_{inj.table}_{cid_col}" if cid_col else f"{inj.type}_{inj.table}"
    return {
        "id": cid,
        "text": f"{inj.table}.{column or '-'} {desc}，根因{inj.root_cause_category}，整改{remedy}",
        "type": inj.type,
        "root_cause": inj.root_cause_category,
        "table": inj.table,
        "column": column or None,
    }


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
    """案例库 = 静态注入案例（`{type}_{table}` 种子）+ 数据飞轮回流案例（`{type}_{table}_{column}` 增量）。

    飞轮 id 含 column、静态 id 不含，两者天然不冲突 → 飞轮只增不覆盖，静态的 desc/remedy 不再被顶掉。
    若未来出现同 id（如人工回灌），仍按飞轮版本覆盖。
    """
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
