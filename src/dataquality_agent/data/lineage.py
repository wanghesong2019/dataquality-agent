"""表级血缘元数据（自建，硬编码数据依赖关系）。

分两类边，都用「子表 -> [父表]」表达「子表的数据依赖哪些上游表」：
1. FK 依赖（子表外键 → 父表）：归因 Agent 用 lineage 工具追根因（如 orphan 往上溯源），
   检测层 check_orphan 逐对兜底（detection/rules.py:120-125）。
2. 构建血缘（下游表 → 上游表）：ODS → DWD（类型规范化）→ DWS（聚合），对齐 warehouse.py
   真正 build 出来的表。

血缘断裂检测（detect_lineage_break）只该查「构建血缘」（下游是 build 出来的、与上游同日期轴），
不该查 FK 依赖——order_items→orders 是引用关系，最新订单可能还没订单项/评价，这是自然现象不是停更。
所以提供两个查询：upstream()（FK + 构建，归因溯源用）和 build_upstream()（仅构建，检测用）。

生产该从数仓元数据自动采集（dbt/OpenLineage），这里是 demo 硬编码。
"""

# FK 依赖（归因溯源用；与 check_orphan 的逐对校验对齐）
_FK_LINEAGE: dict[str, list[str]] = {
    "order_items": ["orders", "products", "sellers"],
    "payments": ["orders"],
    "reviews": ["orders"],
}

# 构建血缘：ODS → DWD（类型规范化，TRY_CAST）→ DWS（聚合）
_BUILD_LINEAGE: dict[str, list[str]] = {
    "dwd_orders": ["orders"],
    "dwd_order_items": ["order_items"],
    "dwd_payments": ["payments"],
    "dwd_reviews": ["reviews"],
    "dwd_products": ["products"],
    "dwd_sellers": ["sellers"],
    "dwd_customers": ["customers"],
    "dwd_geolocation": ["geolocation"],
    "daily_metrics": ["orders", "order_items"],
    "seller_metrics": ["order_items", "dwd_reviews"],
    "category_metrics": ["order_items", "products"],
    "payment_summary": ["dwd_payments"],
}

# 合并（upstream/downstream/all_edges 用，向后兼容）
_TABLE_LINEAGE: dict[str, list[str]] = {**_FK_LINEAGE, **_BUILD_LINEAGE}


class Lineage:
    """表级血缘查询：上游（FK+构建）/ 构建上游 / 下游 / 全部边。"""

    def upstream(self, table: str) -> list[str]:
        """全部上游（FK 依赖 + 构建血缘），归因 Agent 溯源用。"""
        return _TABLE_LINEAGE.get(table, [])

    def build_upstream(self, table: str) -> list[str]:
        """仅构建血缘上游（下游表是 build 出来的），血缘断裂检测用。"""
        return _BUILD_LINEAGE.get(table, [])

    def downstream(self, table: str) -> list[str]:
        """下游（谁依赖它的数据）。"""
        return [child for child, parents in _TABLE_LINEAGE.items() if table in parents]

    def all_edges(self) -> list[tuple[str, str]]:
        """全部血缘边 (上游, 下游)。"""
        edges: list[tuple[str, str]] = []
        for child, parents in _TABLE_LINEAGE.items():
            for parent in parents:
                edges.append((parent, child))
        return edges
