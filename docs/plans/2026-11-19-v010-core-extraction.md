# DataAgent v0.1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 DuckDB 硬绑定的 demo，抽成「可 `pip install` + `dqagent` CLI + `WarehouseAdapter` 可插拔」的开箱即用内核，并完成 HITL 持久化与开源基线，产出 `v0.1.0` 标签。

**Architecture:** 引入 `WarehouseAdapter` 协议（连接/只读查询/元数据），内核所有代码只通过 adapter 碰数仓；检测层抽成内部 `Detector` 协议 + registry（L0/L1/L2 为首批内置检测器）；`SafeSQL` 从包 DuckDB conn 改为包 adapter；`PatrolRuntime` 增加持久 run store 支持重启恢复；新增 `dqagent` CLI（init/run/detect/eval）。

**Tech Stack:** Python ≥3.10、DuckDB、LangGraph(+checkpoint-sqlite)、FastAPI、Pydantic、pytest、setuptools(src layout)。

**Spec:** `docs/specs/2026-11-19-v010-design.md`（终稿，含 §11 评审决议）。归因设计参考 `docs/design/2026-11-19-attribution-rca-survey.md`。

## Global Constraints

- Python ≥ 3.10（pyproject `requires-python`）。
- 命名三合一：pip 包 `dataquality-agent`、import `dataquality_agent`、CLI `dqagent`（§11 决议⑥）。
- License = Apache-2.0。
- SemVer：0.x 允许 breaking；1.0 才冻结接口。
- **中间态边界**：adapter 拥有连接/只读查询/元数据；内置检测器是 DuckDB 参考实现（可插拔 `Detector` 单元）；**不做 SQL 方言翻译层**（§11 决议①）。
- Detector 用**内部 registry**（非 `entry_points` 公开插件，§11 决议⑤）。
- 阈值接线：`Settings.zscore_threshold / distribution_alpha / null_rate_threshold` 必须从死配置改为实际生效。
- 无 LLM 的 detect-only 模式必须存在（只跑 L0/L1，不依赖 key / embedding）。
- CI 硬门禁 = 无 LLM 的确定性检测 eval；带 LLM 方差的指标不进 CI。

## Review Focus

以下五类输入/失败模式是 spec 隐含但最易咬人的，逐条在所属任务里补测试：

1. **空数仓**：adapter 对着无表的库，`list_tables()/describe_table()/row_count()` 应返回空而非崩溃 → 任务 1。
2. **检测器抛异常**：registry 里某个 detector 失败，`run_detection` 应隔离失败、不拖垮整次巡检 → 任务 3。
3. **checkpoint 文件不存在时重启**：`list_runs()/approve()` 应返回空/404，不抛 500 → 任务 5。
4. **`dqagent init` 目录已存在**：不得覆盖用户已有配置/数据（幂等或明确提示）→ 任务 6。
5. **`dqagent detect` 无数据**：应给出指向 `init` 的可行动错误，而非裸异常 → 任务 6。

---

## File Structure（目标结构）

```
src/dataquality_agent/
  adapters/__init__.py        # 导出 WarehouseAdapter / DuckDBAdapter
  adapters/base.py            # WarehouseAdapter(Protocol)
  adapters/duckdb.py          # DuckDBAdapter（吸收 tools/metadata 的 DESCRIBE/information_schema）
  detection/base.py           # Detector(Protocol) + DETECTORS registry
  cli.py                      # dqagent 入口（init/run/detect/eval）
  api/runtime.py              # + RunStore（持久 run 元数据）
  tools/sql.py                # SafeSQL 改为包 adapter
  ...（其余模块原地收敛到 adapter）
pyproject.toml                # + [project.scripts] dqagent
```

---

## Task 1: WarehouseAdapter 协议 + DuckDBAdapter 参考实现

**Files:**
- Create: `src/dataquality_agent/adapters/__init__.py`
- Create: `src/dataquality_agent/adapters/base.py`
- Create: `src/dataquality_agent/adapters/duckdb.py`
- Create: `tests/test_adapters.py`

**Interfaces:**
- Produces（后续任务依赖）:
```python
# adapters/base.py
class WarehouseAdapter(Protocol):
    def execute(self, sql: str) -> list[tuple]: ...           # 原始只读查询（detector 内部用）
    def list_tables(self) -> list[str]: ...
    def describe_table(self, table: str) -> dict[str, str]: ...  # 列名 -> 类型
    def row_count(self, table: str) -> int: ...

# adapters/duckdb.py
class DuckDBAdapter:
    def __init__(self, path: str | Path): ...
    def connect(self) -> None: ...
    def close(self) -> None: ...
    # 实现上述 4 个方法
```

- [ ] **Step 1: 写失败测试** `tests/test_adapters.py`：用 `mini_warehouse` fixture，断言 `DuckDBAdapter` 的 `list_tables()` 含 `dwd_orders/daily_metrics`；`describe_table("dwd_orders")` 返回非空 dict；`row_count("orders")>0`；`execute("SELECT 1")` 返回 `[(1,)]`。空库 case（Review Focus #1）：新 duckdb 文件 `list_tables()==[]`、`describe_table("x")=={}`。

- [ ] **Step 2: 跑测试确认失败**：`pytest tests/test_adapters.py -v` → FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现** `adapters/base.py` + `adapters/duckdb.py`。`DuckDBAdapter.describe_table` 用 `DESCRIBE`、`list_tables` 用 `information_schema.tables`（即迁移 `tools/metadata.py` 的现有逻辑），`execute` 委托 `conn.execute(sql).fetchall()`。

- [ ] **Step 4: 跑测试通过**：`pytest tests/test_adapters.py -v` → PASS。

- [ ] **Step 5: Commit**：`feat(adapters): add WarehouseAdapter protocol and DuckDBAdapter`

---

## Task 2: SafeSQL / metadata / tooling / remediate 收敛到 adapter

**Files:**
- Modify: `src/dataquality_agent/tools/sql.py`（SafeSQL 收 adapter）
- Modify: `src/dataquality_agent/tools/metadata.py`（改为对 adapter 的薄包装，或删除并迁移调用方）
- Modify: `src/dataquality_agent/agents/tooling.py`（`build_sql_tool`/`build_schema_tool` 收 adapter；`SHOW TABLES`→`adapter.list_tables()`）
- Modify: `src/dataquality_agent/agents/remediate.py`（`SHOW TABLES`→`adapter.list_tables()`）
- Modify: `tests/test_tools.py`、`tests/test_tooling.py`、`tests/test_remediate.py`（传 adapter）

**Interfaces:**
- Consumes: `WarehouseAdapter`（任务 1）。
- Produces:
```python
class SafeSQL:
    def __init__(self, adapter: WarehouseAdapter, whitelist: set[str], max_rows: int = 10000): ...
    def run(self, sql: str) -> list[tuple]: ...   # 护栏校验后 adapter.execute
```

- [ ] **Step 1: 写失败测试** 更新 `test_tools.py`：`SafeSQL(adapter, whitelist)` 构造（不再传 conn）；`SafeSQL.run` 仍拒绝非 SELECT/多语句/白名单外表；`metadata` 调用改为 `adapter.describe_table/list_tables` 断言。

- [ ] **Step 2: 跑测试确认失败**：`pytest tests/test_tools.py -v` → FAIL（签名不匹配）。

- [ ] **Step 3: 实现** SafeSQL 改包 adapter；`tooling.build_schema_tool(adapter)`/`build_sql_tool(adapter, ...)`；`remediate` 的 `SHOW TABLES` 换成 `adapter.list_tables()`。`validate_sql` 逻辑不变。

- [ ] **Step 4: 跑测试通过**：`pytest tests/test_tools.py tests/test_tooling.py tests/test_remediate.py -v` → PASS。

- [ ] **Step 5: Commit**：`refactor(tools): SafeSQL and tooling consume WarehouseAdapter`

---

## Task 3: Detector 协议 + registry + run_detection 收 adapter + 阈值接线

**Files:**
- Create: `src/dataquality_agent/detection/base.py`
- Modify: `src/dataquality_agent/detection/runner.py`（`run_detection(adapter, ...)`）
- Modify: `src/dataquality_agent/detection/rules.py`、`stats.py`、`semantic.py`（各函数收 adapter）
- Modify: `src/dataquality_agent/config.py`（阈值不再死配置）
- Modify: `tests/test_runner.py`、`tests/test_rules.py`、`tests/test_stats.py`、`tests/test_semantic.py`

**Interfaces:**
- Consumes: `WarehouseAdapter`。
- Produces:
```python
# detection/base.py
class Detector(Protocol):
    name: str
    def detect(self, adapter: WarehouseAdapter, ctx: DetectionContext) -> list[Anomaly]: ...

DETECTORS: dict[str, Detector]  # 注册 {"l0": ..., "l1": ..., "l2": ...}

# runner.py
def run_detection(adapter: WarehouseAdapter, detectors: dict[str, Detector] | None = None, *,
                  current_date: str | None = None, expected_schema: dict | None = None,
                  semantic_model=None, zscore_threshold: float | None = None,
                  distribution_alpha: float | None = None) -> DetectionReport
```
- 阈值接线：`zscore_threshold/distribution_alpha` 缺省时从 `Settings` 取；`null_rate_threshold` 传进 `rules.check_null_rate`。

- [ ] **Step 1: 写失败测试** `test_runner.py` 新增：`run_detection(adapter)` 在 `mini_warehouse` 上检出 duplicate；registry 隔离（Review Focus #2）：注册一个 `raise RuntimeError` 的假 detector，`run_detection` 仍返回、其它 detector 结果保留、stats 记一条失败。

- [ ] **Step 2: 跑测试确认失败**：`pytest tests/test_runner.py -v` → FAIL（旧签名是 conn）。

- [ ] **Step 3: 实现** 三个检测文件把 `conn: DuckDBPyConnection` 参数全改为 `adapter`，方言 SQL 改走 `adapter.execute`；runner 组装 DETECTORS 并 try/except 隔离；阈值从 Settings 接线。

- [ ] **Step 4: 跑测试通过**：`pytest tests/test_runner.py tests/test_rules.py tests/test_stats.py tests/test_semantic.py -v` → PASS。

- [ ] **Step 5: Commit**：`refactor(detection): Detector protocol + registry + adapter-based run_detection`

---

## Task 4: agents / eval / scripts 收敛到 adapter（移除内核裸 DuckDB conn）

**Files:**
- Modify: `src/dataquality_agent/agents/inspect.py`、`specialists.py`（`make_sql_agent`）、`remediate.py`、`diagnose.py`（如需）
- Modify: `src/dataquality_agent/eval/harness.py`（`apply_remediation` 收 adapter）
- Modify: `src/dataquality_agent/api/wiring.py`（`build_runtime` 组装 DuckDBAdapter）
- Modify: `scripts/run_eval.py`、`scripts/run_eval_supervisor.py`（基线 SQL 走 adapter）
- Modify: 相关测试

**Interfaces:**
- Consumes: `WarehouseAdapter`、`run_detection(adapter, ...)`。
- Produces: `build_runtime(settings) -> PatrolRuntime` 内部创建 `DuckDBAdapter(settings.db_path)` 并注入所有节点；内核不再 import `duckdb` 的 `DuckDBPyConnection` 类型。

- [ ] **Step 1: 写失败测试** 全量回归 + 一个守卫：`grep -rn "duckdb.DuckDBPyConnection" src/dataquality_agent --include=*.py` 只在 `adapters/` 内出现（`test_config.py` 或 CI 脚本断言）。

- [ ] **Step 2: 跑测试确认失败**：全量 `pytest -q` 部分 FAIL（闭包签名变了）。

- [ ] **Step 3: 实现** 把 `conn` 闭包注入点改为 `adapter`；`eval/harness.apply_remediation(adapter, ...)`；scripts 的 `::DATE`/`DESCRIBE` 改 `adapter.execute`；删除内核模块里的 `import duckdb`（只留 adapters）。

- [ ] **Step 4: 跑测试通过**：`pytest -q` → 全绿（186 用例基线）。

- [ ] **Step 5: Commit**：`refactor: route agents/eval/scripts through WarehouseAdapter`

---

## Task 5: PatrolRuntime 持久化（重启后 list/approve）

**Files:**
- Modify: `src/dataquality_agent/api/runtime.py`（加 RunStore）
- Modify: `src/dataquality_agent/api/wiring.py`（RunStore 用同一 sqlite）
- Modify: `tests/test_api.py`（+ 重启恢复测试）

**Interfaces:**
- Produces:
```python
class RunStore:
    def __init__(self, path: str): ...          # 同一 checkpoint sqlite 或独立表
    def save(self, run_id: str, status: str, config: dict) -> None: ...
    def load(self, run_id: str) -> dict | None: ...
    def list_ids(self) -> list[str]: ...

class PatrolRuntime:
    def __init__(self, graph, run_store: RunStore): ...
    def trigger(...) / get(...) / approve(...) / list_runs(...)   # 改走 RunStore
```

- [ ] **Step 1: 写失败测试** `test_api.py` 新增：`r1 = build_runtime(s); r1.trigger("abc")` → 用同一 `checkpoint_path` 新建 `r2 = build_runtime(s)` → `"abc" in r2.list_runs()` 且 `r2.approve("abc", {"0":"approved"})` 不抛。空 store（Review Focus #3）：新路径 `list_runs()==[]`、`get("nope")` 抛 KeyError→404。

- [ ] **Step 2: 跑测试确认失败**：`pytest tests/test_api.py -v` → FAIL（`_runs` 内存丢）。

- [ ] **Step 3: 实现** RunStore 用 `sqlite3`（复用 checkpoint 库或独立 `.db`），`trigger/get/approve/list_runs` 改读写 RunStore；`approve` 恢复所需 config 从 RunStore 取。

- [ ] **Step 4: 跑测试通过**：`pytest tests/test_api.py -v` → PASS。

- [ ] **Step 5: Commit**：`feat(api): persistent run store for restart-safe list/approve`

---

## Task 6: dqagent CLI + 开箱即用（init / run / detect / eval）

**Files:**
- Create: `src/dataquality_agent/cli.py`
- Create: `src/dataquality_agent/data/sample.py`（样本数据生成器，复用 `tests/conftest.py` 的 mini_data 逻辑）
- Modify: `pyproject.toml`（`[project.scripts] dqagent = "dataquality_agent.cli:main"`）
- Create: `tests/test_cli.py`

**Interfaces:**
- Produces:
```python
# cli.py
def main(argv: list[str] | None = None) -> int: ...
# 子命令：init(生成 .env 默认值 + 样本数据到本地)、run(全链路 patrol)、detect(无 LLM L0/L1)、eval(确定性)
```

- [ ] **Step 1: 写失败测试** `test_cli.py`：`main(["init","--dir", tmp])` 生成样本数据 + 本地 config，且 `Settings(data_dir=...)` 可加载；`init` 幂等（Review Focus #4：已存在时不覆盖）；`main(["detect","--dir", tmp])` 无 key 跑通并输出异常；`detect` 无数据时（Review Focus #5）返回非零 + 提示 `init`。

- [ ] **Step 2: 跑测试确认失败**：`pytest tests/test_cli.py -v` → FAIL（无 cli 模块 / 无入口点）。

- [ ] **Step 3: 实现** 用 `argparse`（不引额外依赖）；`detect` = `run_detection(adapter)` 只跑 L0/L1（`semantic_model=None`）；`init` 写 `.env.example` 副本 + `sample.py` 生成的迷你 Olist CSV。

- [ ] **Step 4: 跑测试通过**：`pytest tests/test_cli.py -v` → PASS；`pip install -e .` 后 `dqagent --help` 可运行。

- [ ] **Step 5: Commit**：`feat(cli): dqagent init/run/detect/eval + sample data`

---

## Task 7: 无 LLM 确定性 eval 进 CI

**Files:**
- Modify: `scripts/run_eval.py`（+ `--no-llm` 模式：只跑检测 F1，跳过归因/整改/端到端）
- Modify: `src/dataquality_agent/eval/harness.py`（`run_eval` 支持 `llm=False` 时归因/整改字段留空）
- Create: `.github/workflows/ci.yml`
- Modify: `README.md`（数字与 CI 一致；测试数改 186）

**Interfaces:**
- Consumes: `run_detection(adapter, ...)`、`evaluate_detection`。
- Produces: CI 硬门禁 = `pytest -q` 全绿 + `python scripts/run_eval.py --no-llm` 检测 F1 ≥ 阈值（0.9）且 exit 0。

- [ ] **Step 1: 写失败测试** `test_eval.py` 新增：`run_eval(..., llm=False)` 时 `attribution_accuracy/remediation_success` 为 `None`、`detection.f1` 正常。

- [ ] **Step 2: 跑测试确认失败**：`pytest tests/test_eval.py -v` → FAIL。

- [ ] **Step 3: 实现** `run_eval` 加 `llm` 开关；`run_eval.py --no-llm` 跳过 LLM 阶段；CI workflow（`actions/checkout` + `setup-python 3.11` + `pip install -e ".[dev]"` + `pytest -q` + `python scripts/run_eval.py --no-llm`）。

- [ ] **Step 4: 跑测试通过**：`pytest tests/test_eval.py -v` → PASS；本地 `python scripts/run_eval.py --no-llm` exit 0。

- [ ] **Step 5: Commit**：`ci: deterministic no-LLM eval gate + GitHub Actions`

---

## Task 8: 开源基线（README / CHANGELOG / LICENSE / tag）

**Files:**
- Modify: `README.md`（英文 + 架构图 + 快速开始 + 评测数字）
- Create: `CHANGELOG.md`、`LICENSE`（Apache-2.0 全文）
- Create: `docs/architecture.png` 或 README 内 Mermaid 架构图

**Interfaces:** 无代码接口。

- [ ] **Step 1: 英文 README**：一句话定位 + Quickstart（`pip install -e .` → `dqagent init` → `dqagent detect` → `dqagent run`）+ 架构图 + 评测表（检测 F1 / 归因 / 整改，标注无 LLM 与带 LLM 两档）+ Apache-2.0 badge。

- [ ] **Step 2: CHANGELOG**：`## [0.1.0] - 2026-11-19` 列出本版 8 个任务的摘要。

- [ ] **Step 3: LICENSE**：Apache-2.0 标准全文。

- [ ] **Step 4: 打 tag**：`git tag v0.1.0`（待用户确认 git 历史审计干净后）。

- [ ] **Step 5: Commit**：`docs: open-source baseline (README/CHANGELOG/LICENSE)`

---

## Self-Review 记录

- **Spec 覆盖**：§8 包含 7 项 → 任务 1-8 全覆盖（内核抽取=T1-4、adapter=T1、CLI+开箱即用=T6、checkpointer=T5、CI eval=T7、开源基线=T8）；§11 决议①→T1-T4 中间态、⑤→T3 内部 registry、④→T5、②→T6、③→T7、⑥→T8。
- **类型一致性**：`WarehouseAdapter` 4 方法签名在 T1 定义、T2-T7 复用；`run_detection(adapter, ...)` 在 T3 定义、T4/T6/T7 复用；`RunStore` 在 T5 定义。
- **Review Focus**：5 条分别落在 T1/T3/T5/T6/T6，均有对应测试。
- **比例**：计划不含函数体实现，只锁签名 + 测试名 + 验收命令。
