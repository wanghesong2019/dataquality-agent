"""表级血缘元数据（自建，硬编码外键依赖关系）。"""

# 子表 -> [父表]（父表是子表外键的来源）
_TABLE_LINEAGE: dict[str, list[str]] = {
    "order_items": ["orders", "products", "sellers"],
    "payments": ["orders"],
    "reviews": ["orders"],
    "daily_metrics": ["orders", "order_items"],
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
