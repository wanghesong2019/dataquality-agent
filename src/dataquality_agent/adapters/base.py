"""WarehouseAdapter 协议：内核访问数仓的唯一抽象。"""
from typing import Protocol


class WarehouseAdapter(Protocol):
    """数仓适配器接口（连接 / 只读查询 / 元数据）。"""

    def execute(self, sql: str) -> list[tuple]:
        """执行 SQL，返回行列表。"""
        ...

    def list_tables(self) -> list[str]:
        """所有表名。"""
        ...

    def describe_table(self, table: str) -> dict[str, str]:
        """返回 {列名: 类型}；表不存在返回空 dict。"""
        ...

    def row_count(self, table: str) -> int:
        """行数；表不存在返回 0。"""
        ...
