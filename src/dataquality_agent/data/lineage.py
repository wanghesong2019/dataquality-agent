"""表级血缘元数据（自建，硬编码数据依赖关系）。

分两类边，都用「子表 -> [父表]」表达「子表的数据依赖哪些上游表」：
1. FK 依赖（子表外键 → 父表）：归因 Agent 用 lineage 工具追根因（如 orphan 往上溯源），
   检测层 check_orphan 逐对兜底（detection/rules.py:120-125）。
2. 构建血缘（下游表 → 上游表）：ODS → DWD（类型规范化）→ DWS（聚合），对齐 warehouse.py
   真正 build 出来的表——Lineage.upstream("seller_metrics") 能答出它的源头在哪。

生产该从数仓元数据自动采集（dbt/OpenLineage），这里是 demo 硬编码。
"""

# 子表 -> [父表]（父表 = 子表的数据来源：FK 来源 或 构建来源）
_TABLE_LINEAGE: dict[str, list[str]] = {
    # --- FK 依赖（归因溯源用；与 check_orphan 的逐对校验对齐）---
    "order_items": ["orders", "products", "sellers"],
    "payments": ["orders"],
    "reviews": ["orders"],
    # --- 构建血缘：ODS → DWD（类型规范化，TRY_CAST）---
    "dwd_orders": ["orders"],
    "dwd_order_items": ["order_items"],
    "dwd_payments": ["payments"],
    "dwd_reviews": ["reviews"],
    "dwd_products": ["products"],
    "dwd_sellers": ["sellers"],
    "dwd_customers": ["customers"],
    "dwd_geolocation": ["geolocation"],
    # --- 构建血缘：DWD/ODS → DWS（聚合）---
    "daily_metrics": ["orders", "order_items"],
    "seller_metrics": ["order_items", "dwd_reviews"],
    "category_metrics": ["order_items", "products"],
    "payment_summary": ["dwd_payments"],
}


class Lineage:
    """表级血缘查询：上游 / 下游 / 全部边。"""

    def upstream(self, table: str) -> list[str]:
        """返回 table 的上游表（它的数据依赖谁）。"""
        return _TABLE_LINEAGE.get(table, [])

    def downstream(self, table: str) -> list[str]:
        """返回 table 的下游表（谁依赖它的数据）。"""
        return [child for child, parents in _TABLE_LINEAGE.items() if table in parents]

    def all_edges(self) -> list[tuple[str, str]]:
        """返回全部血缘边 (上游, 下游)。"""
        edges: list[tuple[str, str]] = []
        for child, parents in _TABLE_LINEAGE.items():
            for parent in parents:
                edges.append((parent, child))
        return edges
