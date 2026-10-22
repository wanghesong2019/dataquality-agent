"""轨迹评测：用 evidence_chain（真实工具调用历史）评「归因过程走得对不对」。

为什么需要它
------------
Outcome 评测（F1 / 归因正确率）只看「最终答案对不对」，但 Agent 和普通 LLM 最大的区别在
「过程」——工具选得对不对、是不是先查 schema 再写 SQL、有没有冗余 loop。一个答案碰巧对的
Agent，可能重复查了 3 次、跳过 schema 直接写 SQL：这是 process 层面的坏，outcome 看不出。
轨迹评测补的就是这一层（对应 2026 质量工程文档的 Trajectory Evaluation）。

设计边界（它不做什么）
--------------------
- 只做**规则化**评估（确定性、0 LLM、可测试），不做 LLM-as-a-Judge 的轨迹打分（那是更重的一层）。
- 只评「过程形态」：无冗余 / schema 优先 / 证据充分；不评「工具选得语义上对不对」（那要结合
  ground-truth 的期望工具序列，暂缓）。
- evidence_chain 格式由 diagnose.py 维护（diagnose.py:137 记 f"{name}({args}) -> {result}"），
  本模块只解析、不修改。
"""
from dataclasses import dataclass, field


@dataclass
class TrajectoryVerdict:
    """单条归因轨迹的过程质量判定。"""

    total_calls: int                 # 工具调用总次数
    unique_tools: int                # 用了几个不同工具
    redundant_calls: int             # 冗余重复调用次数（同工具同参数）
    schema_before_sql: bool | None   # 用了 sql 时：是否先查 schema；没用 sql 为 None（不适用）
    evidence_sufficient: bool        # 是否用了 ≥2 个不同工具（证据充分性启发式）
    passed: bool                     # 综合：无冗余 + schema 优先（硬规则）
    reasons: list[str] = field(default_factory=list)  # 未通过的扣分点


@dataclass
class TrajectoryReport:
    """一次巡检所有归因轨迹的汇总。"""

    evaluated: int                   # 评估的轨迹数
    pass_rate: float                 # 过程合格率
    avg_calls: float                 # 平均工具调用次数
    total_redundant: int             # 冗余调用总数
    schema_before_sql_rate: float | None  # 用了 sql 的轨迹里 schema 优先比例（无 sql 为 None）


def _parse_tool_calls(evidence_chain: list[str]) -> list[tuple[str, str]]:
    """从 evidence_chain（f"{name}({args}) -> {result}"）解析出 (name, args) 序列。"""
    calls: list[tuple[str, str]] = []
    for entry in evidence_chain:
        left = entry.split(" -> ", 1)[0]         # "name(args)"
        name = left.split("(", 1)[0]             # "name"
        calls.append((name, left[len(name):]))   # args 含括号，用于区分同工具不同表
    return calls


def evaluate_trajectory(evidence_chain: list[str]) -> TrajectoryVerdict:
    """规则化评估一条归因轨迹：无冗余 / schema 优先 / 证据充分（返回 TrajectoryVerdict）。

    重难点一：`schema_before_sql` 是三态（bool | None），不是两态
    ----------------------------------------------------------------
    「写 SQL 前先查 schema」这条规则有适用前提——轨迹里用了 sql。所以分三态：
    - None = 没用 sql，规则不适用（默认值，靠下方 `if "sql" in names` 守卫）；
    - True = 用了 sql 且 schema 在 sql 之前（顺序对）；
    - False = 用了 sql 但没先查 schema（顺序错）。
    判断先后用 `names.index()` 取「第一次出现」的位置：只需比第一次调 schema 是否早于第一次
    调 sql。schema 可能压根没调过，`index` 找不到会抛 ValueError，所以用三元表达式兜底成 -1
    （-1 是「不存在」的哨兵，下方 `first_schema != -1` 判的就是它）。

    举例（names = 按调用顺序的工具名）：
    - `["schema","lineage","sql","cases"]` → first_schema=0 < first_sql=2 → **True**（先 schema 后 sql）
    - `["sql","lineage"]` → 没查 schema，first_schema=-1 → `-1 != -1` 为 False → **False**（没先查 schema）
    - `["sql","schema"]` → first_schema=1 > first_sql=0 → `1 < 0` 为 False → **False**（顺序反了）
    - `["schema","lineage","cases"]` → 没用 sql → **None**（规则不适用）

    重难点二：`passed = not reasons` 是「扣分列表」模式
    -------------------------------------------------
    reasons 收集所有违反的硬规则（冗余重复调用 / 用 sql 前没查 schema），利用 Python 空列表
    falsy 的特性：reasons 空 → passed=True，非空 → passed=False（等价 len(reasons)==0）。
    `schema_before_sql is False` 用 `is False` 而非 `if schema_before_sql`，是为了显式区分
    「违反(False)」和「不适用(None)」——只有违反才扣分。reasons 一石二鸟：既决定 passed，
    又作为 TrajectoryVerdict.reasons 返回，让「为什么不通过」可解释。

    设计哲学：过程评测只做可枚举的硬规则（确定性、0 LLM），且 fail-closed——任一硬规则违反
    就不通过（评测要严格，不打宽松分）。「证据充分」（unique >= 2）只作为报告项，不参与硬
    判定——不同异常复杂度不同，不能一刀切。
    """
    calls = _parse_tool_calls(evidence_chain)
    names = [n for n, _ in calls]
    total = len(calls)
    unique = len(set(names))

    # 冗余：同 (name, args) 出现 >1 次（重复查同一张表 = 浪费预算）
    seen: dict[tuple[str, str], int] = {}
    for c in calls:
        seen[c] = seen.get(c, 0) + 1
    redundant = sum(v - 1 for v in seen.values() if v > 1)

    # schema 是否在 sql 之前（仅当用了 sql 时适用）
    schema_before_sql: bool | None = None
    if "sql" in names:
        first_schema = names.index("schema") if "schema" in names else -1
        first_sql = names.index("sql")
        schema_before_sql = first_schema != -1 and first_schema < first_sql

    evidence_sufficient = unique >= 2

    reasons: list[str] = []
    if redundant > 0:
        reasons.append(f"{redundant} 次冗余重复调用")
    if schema_before_sql is False:
        reasons.append("用 sql 前未先查 schema")
    passed = not reasons

    return TrajectoryVerdict(
        total_calls=total, unique_tools=unique, redundant_calls=redundant,
        schema_before_sql=schema_before_sql, evidence_sufficient=evidence_sufficient,
        passed=passed, reasons=reasons,
    )


def evaluate_trajectories(diagnoses) -> TrajectoryReport:
    """对一组 Diagnosis 的 evidence_chain 做轨迹评测，汇总成报告。"""
    verdicts = [evaluate_trajectory(d.evidence_chain) for d in diagnoses]
    if not verdicts:
        return TrajectoryReport(evaluated=0, pass_rate=0.0, avg_calls=0.0,
                                total_redundant=0, schema_before_sql_rate=None)
    evaluated = len(verdicts)
    passed = sum(1 for v in verdicts if v.passed)
    avg_calls = sum(v.total_calls for v in verdicts) / evaluated
    total_redundant = sum(v.redundant_calls for v in verdicts)

    sql_verdicts = [v for v in verdicts if v.schema_before_sql is not None]
    schema_rate = None
    if sql_verdicts:
        schema_rate = sum(1 for v in sql_verdicts if v.schema_before_sql) / len(sql_verdicts)

    return TrajectoryReport(
        evaluated=evaluated, pass_rate=passed / evaluated, avg_calls=avg_calls,
        total_redundant=total_redundant, schema_before_sql_rate=schema_rate,
    )
