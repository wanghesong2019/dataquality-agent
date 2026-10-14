"""历史案例库：喂给归因 Agent 的 cases 工具（混合检索）。"""
from dataquality_agent.rag.embedder import build_embedder
from dataquality_agent.rag.retriever import Retriever

CASES = [
    {"id": "dup_orders", "text": "orders 表 order_id 主键重复，上游 ETL 去重逻辑失效，根因脏数据注入，整改去重 DELETE"},
    {"id": "neg_price", "text": "order_items 价格出现负值，数据录入错误，根因脏数据注入，整改回填正确价格"},
    {"id": "null_delivery", "text": "delivered 订单交付日期为 null，数据采集缺失，根因脏数据注入，整改回填日期"},
    {"id": "orphan_items", "text": "order_items 出现孤儿外键，上游 orders 行被删，根因上游任务失败，整改重跑上游加载"},
]


def build_retriever() -> Retriever:
    """案例检索器：配了 EMBEDDING_* 用 OpenAIEmbedder(BGE-M3)，否则词袋 fallback。"""
    vocab = sorted({w for c in CASES for w in c["text"].split()})
    r = Retriever(build_embedder(vocab))
    r.index(CASES)
    return r
