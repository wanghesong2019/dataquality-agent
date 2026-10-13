"""Pydantic 结构化数据模型（检测/归因/整改/报告的公共契约）。"""
from pydantic import BaseModel


class Anomaly(BaseModel):
    """一条检测出的异常。"""

    type: str  # duplicate / orphan / value_range / null_rate / ...
    table: str
    column: str | None = None
    severity: str = "medium"  # low / medium / high
    evidence: str = ""  # 证据（SQL 结果摘要等）
    metric_value: float | str | None = None
    expected_range: str | None = None
