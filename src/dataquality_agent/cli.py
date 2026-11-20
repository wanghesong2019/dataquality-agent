"""dqagent CLI：开箱即用的命令行入口（init / detect / run / eval）。"""
import argparse
import sys
from pathlib import Path

from dataquality_agent.config import Settings
from dataquality_agent.data.sample import write_sample_data


def _data_dir(args) -> Path:
    return Path(args.dir) / "data"


def _cmd_init(args) -> int:
    data_dir = _data_dir(args)
    if (data_dir / "olist_orders_dataset.csv").exists():
        print(f"样本数据已存在：{data_dir}（幂等，不覆盖）")
    else:
        write_sample_data(data_dir)
        print(f"样本数据已生成：{data_dir}")
    env = Path(args.dir) / ".env"
    if not env.exists():
        env.write_text(f"DATA_DIR={data_dir}\nDB_PATH={data_dir / 'warehouse.duckdb'}\n", encoding="utf-8")
    print(f"下一步：dqagent detect --dir {args.dir}")
    return 0


def _cmd_detect(args) -> int:
    data_dir = _data_dir(args)
    if not (data_dir / "olist_orders_dataset.csv").exists():
        print(f"未找到样本数据（{data_dir}），请先运行：dqagent init --dir {args.dir}", file=sys.stderr)
        return 1
    from dataquality_agent.adapters import DuckDBAdapter
    from dataquality_agent.data.warehouse import Warehouse
    from dataquality_agent.detection.runner import run_detection

    settings = Settings(data_dir=str(data_dir), db_path=str(data_dir / "warehouse.duckdb"))
    Warehouse(settings).build()
    report = run_detection(DuckDBAdapter(settings.db_path))  # 无 semantic_model → 无 LLM
    if report.anomalies:
        for a in report.anomalies:
            print(f"[{a.type}] {a.table}.{a.column or ''} {a.summary}")
    else:
        print("未检出异常")
    print(f"共 {len(report.anomalies)} 条异常")
    return 0


def _cmd_run(args) -> int:
    data_dir = _data_dir(args)
    if not (data_dir / "olist_orders_dataset.csv").exists():
        print(f"未找到样本数据（{data_dir}），请先运行：dqagent init --dir {args.dir}", file=sys.stderr)
        return 1
    from dataquality_agent.api.wiring import build_runtime

    settings = Settings(data_dir=str(data_dir), db_path=str(data_dir / "warehouse.duckdb"),
                        checkpoint_path=str(Path(args.dir) / "checkpoints.sqlite"))
    runtime = build_runtime(settings)
    result = runtime.trigger()
    print(f"run_id={result['run_id']} status={result['status']}")
    return 0


def _cmd_eval(args) -> int:
    data_dir = _data_dir(args)
    if not (data_dir / "olist_orders_dataset.csv").exists():
        print(f"未找到样本数据（{data_dir}），请先运行：dqagent init --dir {args.dir}", file=sys.stderr)
        return 1
    from dataquality_agent.eval.deterministic import run_deterministic_eval

    settings = Settings(data_dir=str(data_dir), db_path=str(data_dir / "warehouse.duckdb"))
    report = run_deterministic_eval(settings)
    d = report.detection
    print(f"检测 P/R/F1：P={d.precision:.3f} R={d.recall:.3f} F1={d.f1:.3f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dqagent", description="数据质量巡检 Agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="生成样本数据 + 本地配置")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("detect", help="无 LLM 检测（L0/L1）")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=_cmd_detect)

    p = sub.add_parser("run", help="完整巡检（需 LLM key）")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("eval", help="确定性评估")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=_cmd_eval)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
