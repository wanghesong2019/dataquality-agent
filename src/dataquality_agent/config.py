"""集中配置：路径、随机种子、检测阈值。"""
from dataclasses import dataclass


@dataclass
class Settings:
    # 路径
    data_dir: str = "/data/home/hermes/olist"
    db_path: str = "/data/home/hermes/projects/dataquality-agent/data/warehouse.duckdb"
    # 可复现性（评估的地基：异常注入必须可复现）
    seed: int = 42
    # L0 阈值
    null_rate_threshold: float = 0.20  # null 率突增阈值
    # L1 阈值
    zscore_threshold: float = 3.0  # volume 异常 Z-score 阈值
    psi_threshold: float = 0.10  # distribution 漂移 PSI 阈值
