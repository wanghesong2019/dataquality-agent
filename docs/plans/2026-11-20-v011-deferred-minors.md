# v0.1.1 Deferred Minors 修复计划

> 目标：清掉 v0.1.0 最终审查留下的 7 个 deferred minors，出一个 patch release（v0.1.1）。
> 执行环境：本地（代码事实源，同步 GitHub）改代码；33-server 跑 pytest（本地无项目依赖）。

## 执行模型

1. 把 33-server 工作树同步到本地 master（scp 覆盖 `src/` + `tests/`）。
2. 每个 fix 走 TDD：先写回归测试 → 33-server 上跑（看它失败）→ 写修复 → 33-server 上跑（看它通过）。
3. 全绿后：本地 commit → 更新 CHANGELOG → 打 tag `v0.1.1` → push。

## 七个 fix

### Fix 1 — `_watermarks` 硬编码 Olist 表，非 Olist 库 run_detection 崩溃
- 文件：`src/dataquality_agent/detection/runner.py:21-37`
- 根因：`_watermarks` 无条件 `SELECT ... FROM dwd_orders / daily_metrics`，表不存在时抛异常；它在 per-detector try/except 之外（runner.py:139），直接炸掉整次巡检。
- 修复：查 `adapter.list_tables()` 判断表存在才查水位线，缺表返回空 dict（下游 L1 已能 no-op/隔离）。
- 测试：`tests/test_runner.py::test_run_detection_non_olist_warehouse_graceful` — 空数仓 `run_detection` 不抛异常。

### Fix 2 — `null_rate_threshold` 死配置（config 0.20 vs 硬编码 0.05）
- 文件：`config.py:16`、`rules.py:75/94/108`、`runner.py`
- 根因：`Settings.null_rate_threshold=0.20` 从未被读；`run_rule_checks` 硬编码 0.05。
- 修复：config 默认改 0.05（对齐真实口径，run_eval 注入也按 5% 标定）；按 `zscore_threshold`/`distribution_alpha` 同款模式穿进 `run_detection` ctx → `_L0Rules` → `run_rule_checks`，替换 delivered-date 检查的硬编码 0.05；customer_id 的 `threshold=0.0`（"任何空值都算"）保持显式。
- 测试：`tests/test_rules.py::test_null_rate_threshold_controls_detection` — 阈值 0.05 检出 / 0.99 不检出。

### Fix 3 — `dqagent eval` 空壳
- 文件：新增 `src/dataquality_agent/eval/deterministic.py`、`cli.py:64-66`
- 根因：`_cmd_eval` 打印"待实现"却 return 0。
- 修复：抽 `run_deterministic_eval(settings, injection_specs)`（建仓→clone→注入→检测→无 LLM EvalReport）+ `SAMPLE_INJECTION_SPECS`（自包含 mini 数据的注入计划）；`_cmd_eval` 调它并打印 F1，成功 return 0。
- 测试：`tests/test_cli.py::test_eval_runs_deterministic_eval` — `main(["eval","--dir",...])` 返回 0 且输出含 F1（非"待实现"）。

### Fix 4 — CI 未跑 F1 门禁
- 文件：新增 `tests/test_deterministic_eval.py`
- 根因：CI 只跑 `pytest -q`，没有把检测 F1 当硬门禁；`run_eval.py --no-llm` 依赖真实 Olist，CI 上跑不了。
- 修复：加 pytest 门禁测试 `test_deterministic_f1_is_perfect` —— 在自包含样本数据上跑 `run_deterministic_eval`，断言 `detection.f1 == 1.0`。CI 的 `pytest -q` 自动纳入，README 的「Detection F1 = 1.0」从此有 CI 背书。

### Fix 5 — `total_latency` 把失败标记 -1.0 计入耗时
- 文件：`src/dataquality_agent/eval/metrics.py:183-185`
- 根因：`sum(stats.values())` 把 `-1.0`（检测器失败标记）当秒数累加。
- 修复：`sum(v for v in stats.values() if v >= 0)`。
- 测试：`tests/test_eval.py::test_total_latency_excludes_failures` — 含 `-1.0` 只算正值。

### Fix 6 — RunStore/SqliteSaver 无锁并发偶发 sqlite locked
- 文件：`src/dataquality_agent/api/runtime.py:26-40`、`api/wiring.py:52`
- 根因：`check_same_thread=False` 无锁，多线程并发写同一连接偶发 locked。
- 修复：`RunStore` 加 `threading.Lock` 包住读写 + `sqlite3.connect(..., timeout=30)`；`wiring.py` 的 SqliteSaver 连接加 `timeout=30`（belt-and-suspenders）。
- 测试：`tests/test_api.py::test_runstore_concurrent_writes` — 20 线程并发 save 无异常、全部落盘。

### Fix 7 — 包装外部 conn 的 adapter close() 后复用静默连内存库
- 文件：`src/dataquality_agent/adapters/duckdb.py:25-28`
- 根因：`close()` 无条件 `self._conn = None`；包装外部 conn（`path=None`）时，复用触发 `duckdb.connect(None)` → 静默连内存库。
- 修复：包装外部 conn（`_owns_conn=False`）时 `close()` 直接 return（不关、不置空，所有权在调用方）。
- 测试：`tests/test_adapters.py::test_wrapped_conn_survives_close_and_reuse` — close 后仍能读外部 conn 的表。

### Doc 8 — 「在你自己的数仓上跑 eval」+ 状态库现状说明
- 文件：新增 `website/docs/how-to/run-eval-on-your-warehouse.md`
- 内容：(1) 换 `settings` 指向自己的数仓 + 自定义 `injection_specs`（n 按数据量标定，如 null_rate 要超 5% 阈值需 n 量级）；(2) 状态库 SQLite 是参考实现、生产换 Postgres 走 v0.2（LangGraph `PostgresSaver`），`CHECKPOINT_PATH` 现在只能改 SQLite 位置、不能换引擎。
- 英文为主（文档站点现英文 + zh-CN 预留）。

## 收尾

- 版本号 0.1.0 → 0.1.1（`pyproject.toml`）。
- CHANGELOG 加 `[0.1.1]` 段。
- 打 tag `v0.1.1`，push master + tag。
