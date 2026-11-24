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
        print(f"Sample data already exists: {data_dir} (idempotent, not overwritten)")
    else:
        write_sample_data(data_dir)
        print(f"Sample data generated: {data_dir}")
    env = Path(args.dir) / ".env"
    if not env.exists():
        env.write_text(f"DATA_DIR={data_dir}\nDB_PATH={data_dir / 'warehouse.duckdb'}\n", encoding="utf-8")
    print(f"Next: dqagent detect --dir {args.dir}")
    return 0


def _cmd_detect(args) -> int:
    data_dir = _data_dir(args)
    if not (data_dir / "olist_orders_dataset.csv").exists():
        print(f"Sample data not found ({data_dir}), run first: dqagent init --dir {args.dir}", file=sys.stderr)
        return 1
    from dataquality_agent.adapters import DuckDBAdapter
    from dataquality_agent.data.warehouse import Warehouse
    from dataquality_agent.detection.runner import run_detection

    settings = Settings(data_dir=str(data_dir), db_path=str(data_dir / "warehouse.duckdb"))
    Warehouse(settings).build()
    report = run_detection(DuckDBAdapter(settings.db_path), assertions_path=args.assertions_path)  # 无 semantic_model → 无 LLM
    if report.anomalies:
        for a in report.anomalies:
            print(f"[{a.type}] {a.table}.{a.column or ''} {a.summary}")
    else:
        print("No anomalies detected")
    print(f"{len(report.anomalies)} anomalies total")
    return 0


def _cmd_run(args) -> int:
    data_dir = _data_dir(args)
    if not (data_dir / "olist_orders_dataset.csv").exists():
        print(f"Sample data not found ({data_dir}), run first: dqagent init --dir {args.dir}", file=sys.stderr)
        return 1
    from dataquality_agent.api.wiring import build_runtime
    from dataquality_agent.report_text import format_run_report

    settings = Settings(data_dir=str(data_dir), db_path=str(data_dir / "warehouse.duckdb"),
                        checkpoint_path=str(Path(args.dir) / "checkpoints.sqlite"))
    runtime = build_runtime(settings)
    result = runtime.trigger()
    state = runtime.get(result["run_id"])["state"]
    print(format_run_report(state))
    print(f"run_id={result['run_id']} status={result['status']}")
    return 0


def _cmd_eval(args) -> int:
    data_dir = _data_dir(args)
    if not (data_dir / "olist_orders_dataset.csv").exists():
        print(f"Sample data not found ({data_dir}), run first: dqagent init --dir {args.dir}", file=sys.stderr)
        return 1
    from dataquality_agent.eval.deterministic import run_deterministic_eval

    settings = Settings(data_dir=str(data_dir), db_path=str(data_dir / "warehouse.duckdb"))
    report = run_deterministic_eval(settings)
    d = report.detection
    print(f"Detection P/R/F1: P={d.precision:.3f} R={d.recall:.3f} F1={d.f1:.3f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dqagent", description="Data quality patrol agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="Generate sample data + local config")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("detect", help="No-LLM detection (L0/L1)")
    p.add_argument("--dir", required=True)
    p.add_argument("--assertions", dest="assertions_path", default=None,
                   help="Declarative L0 assertion catalog YAML path (default: built-in Olist catalog)")
    p.set_defaults(func=_cmd_detect)

    p = sub.add_parser("run", help="Full patrol (needs LLM key)")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("eval", help="Deterministic eval")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=_cmd_eval)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
