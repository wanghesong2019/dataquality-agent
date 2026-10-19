"""集中配置：路径、随机种子、检测阈值。"""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    # 路径（env 可覆盖：DATA_DIR / DB_PATH，方便 Docker 部署）
    data_dir: str = field(default_factory=lambda: os.environ.get("DATA_DIR", "/data/home/hermes/olist"))
    db_path: str = field(default_factory=lambda: os.environ.get("DB_PATH", "/data/home/hermes/projects/dataquality-agent/data/warehouse.duckdb"))
    checkpoint_path: str = field(default_factory=lambda: os.environ.get("CHECKPOINT_PATH", "/data/home/hermes/projects/dataquality-agent/data/checkpoints.sqlite"))
    # 可复现性（评估的地基：异常注入必须可复现）
    seed: int = 42
    # L0 阈值
    null_rate_threshold: float = 0.20  # null 率突增阈值
    # L1 阈值
    zscore_threshold: float = 3.0  # volume 异常 Z-score 阈值
    psi_threshold: float = 0.10  # distribution 漂移 PSI 阈值


def load_env(path) -> None:
    """极简 .env loader（KEY=VALUE，不依赖 python-dotenv；已有环境变量不覆盖）。"""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
