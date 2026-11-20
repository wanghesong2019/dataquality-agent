# v0.2.0 实施计划：证据一等 + 薄 Agent

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「一切皆断言，判断皆有据」落到代码：让 `Evidence` 成为一等公民的数据结构，检测 fail 时抓命中行，把 Agent 从"取证者"收薄为"证据消费者"。

**Architecture:** 一条主链路 `检测（确定性，抓证据）→ 归因（单一 Agent，读证据包）→ 整改 → 审批 → 报告`。关键改造是**取证前移**：L0/L1 检测在判定 fail 时顺手抓 `LIMIT 20` 命中行进结构化 `Evidence`；归因层删掉 supervisor 分诊 + 3 专职，换成"确定性装配证据包 + 单次 LLM 调用"的单一 Agent。

**Tech Stack:** Python 3.11 / Pydantic / LangGraph / DuckDB（测试与运行走 33-server，见下）

**Spec:** `docs/specs/design-philosophy.md` + `docs/specs/2026-11-20-v020-design.md`

**执行说明：** 本地是代码事实源（同步 GitHub）；pytest 在 33-server 跑（本地无依赖），用 connect-33-server skill 的 tar+scp 同步。每个 task 的 RED/GREEN 都在 33-server 验证。

## Global Constraints

- **公理一（断言统一）**：检测/归因/整改产出是同一形状（声明 + 判定 + 证据）。
- **公理二（证据一等）**：任何 fail 的结论必带结构化 `Evidence`；`evidence.rows` 样本 `LIMIT 20` 封顶（token-cheap）。
- **公理三（确定性优先）**：能规则不统计、能统计不 LLM；LLM 只在归因/整改（及 L2 语义）介入，且"输入证据包、输出带证据的结构化结论"。
- **只读护栏不松动**：SafeSQL SELECT-only + 白名单 + 行上限（不改）。
- **按需取证据**：adapter 保持最小四原语（execute/list_tables/describe_table/row_count），不新增 metadata dump。
- **薄 Agent**：无 LLM 分诊、无 3 专职；单一归因 Agent 读证据包下结论。
- **v0.2 不做**：声明式断言目录（v0.3）、Postgres 连接器（v0.3）、SQL 方言翻译、数据侧可观测、公开 entry_points。
- **抽取式改造，不是重写**：保留 `build_supervisor_graph` / `specialists.py` / `supervisor.py` 代码不删（作 eval 对照臂，后续再决定去留）。

## Review Focus

以下五类输入/失败模式，spec 没有显式覆盖，但会咬到真实用户——每个都在对应 task 里补测试钉住：

1. **检测器采样查询自身报错**（如列名含非法字符）→ 不得让整次巡检崩溃（单检测器隔离）。
2. **命中行为空**（COUNT>0 但采样 0 行，如并发/`LIMIT 0`）→ `Evidence.rows` 允许为空列表/None，不得崩。
3. **海量命中**（百万行违规）→ `LIMIT 20` 必须真封顶，不得物化全量。
4. **表级异常无列**（如 `state_conflict` 的 `column` 为 None）→ 证据采集不得假设列存在。
5. **证据包为空**（血缘/cases/schema 都取不到）→ 单一归因 Agent 仍须产出合法 `Diagnosis`（降级"未知"），不得崩。

---

### Task 1: `Evidence` 模型 + `Anomaly` 结构化证据 + 首条规则迁移（模式定型）

**Files:**
- Modify: `src/dataquality_agent/models.py`（加 `Evidence`；`Anomaly.evidence` 类型 str→Evidence）
- Modify: `src/dataquality_agent/detection/rules.py`（`check_duplicate` 迁移为结构化证据 + 采样助手）
- Test: `tests/test_rules.py`

**Interfaces:**
- Produces: `Evidence`（query: str, rows: list[dict] | None, expected: str | None, actual: str | None, lineage: list[str] | None, blast_radius: list[str] | None）；`Anomaly.evidence: Evidence` + `Anomaly.summary`（property，回吐旧文本，兼容字符串消费方）；`sample_offending(adapter, table: str, where_sql: str, limit: int = 20) -> list[dict]`。

- [ ] **Step 1: 写失败测试**

`tests/test_rules.py` 新增（用现有注入重复键的 fixture，见 `tests/conftest.py`）：

```python
def test_duplicate_evidence_structured(adapter_with_duplicates):
    from dataquality_agent.detection.rules import check_duplicate
    from dataquality_agent.models import Evidence
    anomalies = check_duplicate(adapter_with_duplicates, "orders", ["order_id"])
    assert anomalies, "注入重复键后应检出"
    ev = anomalies[0].evidence
    assert isinstance(ev, Evidence)          # 不再是 str
    assert ev.query and ev.query.strip()     # query 非空
    assert ev.rows, "必须抓到命中行样本"      # rows 非空
    assert len(ev.rows) <= 20                # 封顶
    assert "重复" in anomalies[0].summary    # summary 兼容旧文本
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_rules.py::test_duplicate_evidence_structured -v`
Expected: FAIL —— `AttributeError` / `isinstance(ev, Evidence)` 为假（当前 `evidence` 是 str）。

- [ ] **Step 3: 实现**

`models.py`：加 `Evidence(BaseModel)`（字段如上）；`Anomaly.evidence: Evidence`，加 `summary` property（从 `actual`/`expected`/`type` 拼旧文本，格式对齐原 `f"{n} 组重复键"` 一类）。`rules.py`：加 `sample_offending(adapter, table, where_sql, limit=20)`（`SELECT * FROM {table} WHERE {where_sql} LIMIT {limit}`，返回 `list[dict]`，列名从 `adapter.describe_table(table)` 取）；`check_duplicate` 用 COUNT 判 fire、再采样命中行构造 `Evidence(query=..., rows=..., expected="无重复键", actual=f"{n} 组")`。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_rules.py -v`
Expected: PASS（本条 + 既有规则测试仍绿）。

- [ ] **Step 5: Commit**

```bash
git add src/dataquality_agent/models.py src/dataquality_agent/detection/rules.py tests/test_rules.py
git commit -m "feat: add structured Evidence model and migrate duplicate check"
```

---

### Task 2: 迁移其余 L0 规则 + 跨表一致性（结构化证据 + 命中行）

**Files:**
- Modify: `src/dataquality_agent/detection/rules.py`（`check_orphan`/`check_negative`/`check_value_range`/`check_time_inversion`/`check_future_date`/`check_null_rate`/`check_amount_mismatch`/`check_state_conflict`/`check_zip_inconsistency`）
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: `Evidence`、`sample_offending`（Task 1）。
- Produces: 所有 L0 规则返回的 `Anomaly.evidence` 均为 `Evidence` 且 `query` 非空、`rows` 非空（行型规则）或 `expected/actual` 非空（行型规则 `rows` 可为 None，如无列可采样）。

- [ ] **Step 1: 写失败测试**

```python
def test_all_l0_anomalies_carry_evidence(adapter_with_injections):
    from dataquality_agent.detection.rules import run_rule_checks, run_consistency_checks
    from dataquality_agent.models import Evidence
    anomalies = run_rule_checks(adapter_with_injections) + run_consistency_checks(adapter_with_injections)
    fired = [a for a in anomalies]
    assert fired, "注入后应有多条异常"
    for a in fired:
        assert isinstance(a.evidence, Evidence)
        assert a.evidence.query.strip()
        # 行型证据必有 rows；表级/统计型 rows 可为 None，但 expected/actual 至少一项非空
        assert a.evidence.rows or (a.evidence.expected or a.evidence.actual)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_rules.py::test_all_l0_anomalies_carry_evidence -v`
Expected: FAIL —— 其余规则仍返回 `evidence: str`。

- [ ] **Step 3: 实现**

逐条迁移：每条规则保留原 COUNT 判定，fire 时用 `sample_offending` 抓命中行、构造 `Evidence`（`query` 填采样 SQL，`expected`/`actual` 填规则语义）。`null_rate` 的 `rows` 用 `column IS NULL [AND status 分层]` 采样；`amount_mismatch`/`state_conflict` 这类 join 型规则，`where_sql` 填能复现命中的子查询条件（或 `rows=None` 时仅 expected/actual，看实际可采样性）。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_rules.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/dataquality_agent/detection/rules.py tests/test_rules.py
git commit -m "feat: migrate all L0 rules to structured Evidence with row sampling"
```

---

### Task 3: 迁移 L1 统计检测（结构化证据）

**Files:**
- Modify: `src/dataquality_agent/detection/stats.py`（`detect_volume`/`detect_distribution`/`detect_lineage_break`/`detect_freshness`/`detect_schema_drift`）
- Test: `tests/test_rules.py`（或新增 `tests/test_stats.py`）

**Interfaces:**
- Consumes: `Evidence`（Task 1）。
- Produces: L1 异常的 `evidence` 为 `Evidence`；`expected`/`actual` 非空（如 `expected="|z| <= 3"`、`actual="|z|=4.2"`）；无"命中行"概念的（freshness/lineage_break/schema_drift）`rows=None`，但 `query` 或 `expected/actual` 非空。

- [ ] **Step 1: 写失败测试**

```python
def test_l1_anomalies_carry_evidence(adapter_with_drift):
    from dataquality_agent.detection.stats import detect_volume, detect_lineage_break, detect_freshness
    from dataquality_agent.models import Evidence
    # 以 detect_volume + detect_freshness 为代表（lineage_break/schema_drift 同理）
    anomalies = detect_volume(adapter_with_drift) + detect_freshness({}, "2099-01-01")
    for a in anomalies:
        assert isinstance(a.evidence, Evidence)
        assert a.evidence.expected and a.evidence.actual  # 期望 vs 实际非空
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_rules.py::test_l1_anomalies_carry_evidence -v`（或对应文件）
Expected: FAIL —— L1 仍返回 `evidence: str`。

- [ ] **Step 3: 实现**

逐条迁移：`volume`/`distribution` 填 `expected`（阈值/α）+ `actual`（观测 z/p 值）+ `query`；`lineage_break`/`freshness`/`schema_drift` 填 `expected`（容忍天数/快照）+ `actual`（实际滞后/变更）+ `lineage`（涉及的上游表），`rows=None`。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_rules.py tests/test_stats.py -v`（或对应文件）
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/dataquality_agent/detection/stats.py tests/
git commit -m "feat: migrate L1 statistical detectors to structured Evidence"
```

---

### Task 4: `Diagnosis` / `Remediation` 挂证据

**Files:**
- Modify: `src/dataquality_agent/models.py`
- Test: `tests/test_models.py`（或就近）

**Interfaces:**
- Produces: `Diagnosis.evidence: list[Evidence]`（支撑根因的证据，新增；`evidence_chain` 保留作审计轨迹）；`Remediation.evidence: Evidence | None`（提案依据的根因证据，新增）。

- [ ] **Step 1: 写失败测试**

```python
def test_diagnosis_and_remediation_carry_evidence():
    from dataquality_agent.models import Diagnosis, Remediation, Evidence
    d = Diagnosis(root_cause_category="脏数据注入", confidence=0.9, evidence=[Evidence(query="SELECT 1", rows=[])])
    assert isinstance(d.evidence, list) and isinstance(d.evidence[0], Evidence)
    r = Remediation(action_type="fix_sql", sql_or_suggestion="DELETE ...", evidence=d.evidence[0])
    assert isinstance(r.evidence, Evidence)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_models.py::test_diagnosis_and_remediation_carry_evidence -v`
Expected: FAIL —— `Diagnosis`/`Remediation` 无 `evidence` 字段。

- [ ] **Step 3: 实现**

`models.py`：给 `Diagnosis` 加 `evidence: list[Evidence] = Field(default_factory=list)`；给 `Remediation` 加 `evidence: Evidence | None = None`。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_models.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/dataquality_agent/models.py tests/test_models.py
git commit -m "feat: mount Evidence on Diagnosis and Remediation"
```

---

### Task 5: 薄 Agent（确定性取证 + 单一归因）

**Files:**
- Modify: `src/dataquality_agent/agents/diagnose.py`（新增证据装配 + 薄归因节点）
- Modify: `src/dataquality_agent/api/wiring.py`（改用 `build_graph` + 薄归因节点，弃 supervisor）
- Test: `tests/test_api.py`（或新增 `tests/test_attribution.py`）

**Interfaces:**
- Produces: `assemble_evidence(anomaly, adapter, lineage, retriever) -> list[str]`（确定性：`anomaly.evidence` 摘要 + `lineage.upstream(table)` + `adapter.describe_table(table)` + `retriever.search(...)`，全部无 LLM）；`make_thin_diagnose_node(model, adapter, lineage, retriever)`（每异常：装配证据包 → `build_aggregate_diagnose_prompt` → 单次 `submit_diagnosis` 调用 → `Diagnosis`（带 `evidence`），证据包为空时降级 `Diagnosis(root_cause_category="未知", confidence=0.0)`）。证据源当前写死 3 个（血缘/schema/案例），本次留注释不改实现——未来 L2/契约可扩展为证据源列表（见设计文档 §9）。

- [ ] **Step 1: 写失败测试（纯确定性部分，无 LLM）**

```python
def test_assemble_evidence_is_deterministic(adapter, lineage, retriever):
    from dataquality_agent.agents.diagnose import assemble_evidence
    from dataquality_agent.models import Anomaly, Evidence
    a = Anomaly(type="duplicate", table="orders", column="order_id",
                evidence=Evidence(query="SELECT * FROM orders WHERE ...", rows=[{"order_id": "x"}]))
    p1 = assemble_evidence(a, adapter, lineage, retriever)
    p2 = assemble_evidence(a, adapter, lineage, retriever)
    assert p1 == p2 and p1, "证据装配确定性且非空"
```

```python
def test_thin_diagnose_degrades_on_empty_evidence(fake_model, adapter, lineage, retriever):
    from dataquality_agent.agents.diagnose import make_thin_diagnose_node
    from dataquality_agent.models import Anomaly, Evidence
    node = make_thin_diagnose_node(fake_model, adapter, lineage, retriever)
    a = Anomaly(type="weird", table="nope", evidence=Evidence(query="", rows=None))
    out = node({"anomalies": [a]})
    assert out["diagnoses"][0].root_cause_category == "未知"  # 空证据 → 优雅降级，不崩
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_attribution.py -v`
Expected: FAIL —— `assemble_evidence`/`make_thin_diagnose_node` 不存在。

- [ ] **Step 3: 实现**

`diagnose.py`：实现 `assemble_evidence`（返回证据文本行列表，供 prompt 拼装；每个来源失败单独捕获成 `"<source>: 不可用"`，不让整包失败）；实现 `make_thin_diagnose_node`（复用 `_aggregate_one` 的"证据→单次 LLM→Diagnosis"逻辑，把 `evidence` 从"3 专职 finding"换成"`assemble_evidence` 结果"，并回填 `Diagnosis.evidence`）。`wiring.py`：`build_runtime` 里 `build_supervisor_graph(...)` 换成 `build_graph(make_inspect_node(...), make_thin_diagnose_node(...), make_remediate_node(...), make_approve_node(...), make_report_node(...), checkpointer=...)`；移除 triage/3 专职装配（模块保留，不再 import 进 wiring）。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_attribution.py tests/test_api.py -v`
Expected: PASS（薄归因节点 + wiring 装配）。

- [ ] **Step 5: Commit**

```bash
git add src/dataquality_agent/agents/diagnose.py src/dataquality_agent/api/wiring.py tests/
git commit -m "feat: thin attribution — deterministic evidence assembly + single agent"
```

---

### Task 6: 确定性 eval 加证据完整性门禁

**Files:**
- Modify: `src/dataquality_agent/eval/deterministic.py`（或 `tests/test_deterministic_eval.py`）
- Test: `tests/test_deterministic_eval.py`

**Interfaces:**
- Consumes: `run_deterministic_eval`（v0.1.1 已有，F1 门禁）。
- Produces: eval 里对每个 fail 异常断言 `evidence.query` 非空、`rows` ≤ 20（证据完整性，与 F1=1.0 并列）。

- [ ] **Step 1: 写失败测试**

```python
def test_eval_asserts_evidence_completeness(sample_settings):
    from dataquality_agent.eval.deterministic import run_deterministic_eval
    report = run_deterministic_eval(sample_settings)
    assert report.detection.f1 == 1.0
    for a in report.anomalies:            # 证据完整性：所有 fail 异常带证据
        assert a.evidence.query.strip()
        assert a.evidence.rows is None or len(a.evidence.rows) <= 20
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_deterministic_eval.py::test_eval_asserts_evidence_completeness -v`
Expected: FAIL —— `report.anomalies` 尚不可达或证据字段缺失（若 `run_deterministic_eval` 未暴露 anomalies，则在本 task 顺带暴露）。

- [ ] **Step 3: 实现**

`eval/deterministic.py`：让 `run_deterministic_eval` 返回/暴露 `anomalies`（若尚未）；在确定性 eval 里加证据完整性断言（或作为测试侧断言，二选一，取改动最小者）。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_deterministic_eval.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/dataquality_agent/eval/deterministic.py tests/test_deterministic_eval.py
git commit -m "test: gate evidence completeness in deterministic eval"
```

---

## 收尾

- 全部 task 绿后，33-server 跑完整 `pytest`（预期 204 基线 + 本计划新增用例全绿）。
- LLM 侧对比（成本归一成功率 + 归因正确率 vs v0.1.0 基线 0.75 / token 4.4万）走 `scripts/run_eval.py` 在 33-server 闲时手动跑，不进 CI。
- 文档：CHANGELOG 加 [0.2.0]；README/网站待 v0.2.0 落地后按设计哲学一并重构（记忆已记）。
