"""策展 demo 数据集 CLI（服务器上跑，需要全量 Olist）。

用法：cd 项目根 && .venv/bin/python scripts/make_demo_data.py \
        --src /data/home/hermes/olist --out demo --n 5000
产出：demo/data/*.csv（8 表 + translation，含注入的 4 类故障），可直接
      `dqagent detect --dir demo` / `dqagent run --dir demo`。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dataquality_agent.data.demo import build_demo_dataset, write_demo_data


def main() -> None:
    p = argparse.ArgumentParser(description="Curate a realistic demo dataset from the full Olist")
    p.add_argument("--src", required=True, help="directory with the full Olist CSVs")
    p.add_argument("--out", required=True, help="output project dir (writes <out>/data/*.csv)")
    p.add_argument("--n", type=int, default=5000, help="number of orders to sample")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    tables = build_demo_dataset(args.src, n=args.n, seed=args.seed)
    write_demo_data(tables, args.out)
    print(f"demo dataset written to {Path(args.out) / 'data'}: "
          f"{len(tables['orders'])} orders, {len(tables['order_items'])} items, "
          f"{len(tables['products'])} products, {len(tables['geolocation'])} geolocation rows")


if __name__ == "__main__":
    main()
