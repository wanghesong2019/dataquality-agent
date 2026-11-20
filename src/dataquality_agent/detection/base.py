"""检测器协议与注册表。"""
from typing import Protocol

from dataquality_agent.models import Anomaly


class Detector(Protocol):
    """一个可插拔的检测步骤：name + detect(adapter, ctx) -> 异常列表。"""

    name: str

    def detect(self, adapter, ctx: dict) -> list[Anomaly]:
        ...


# 内置检测器注册表（runner.py 启动时填充；顺序即执行顺序）
DETECTORS: dict[str, Detector] = {}
