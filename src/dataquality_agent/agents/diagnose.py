"""归因 Agent：原生 function calling 工具循环，查血缘/案例/SQL → 收敛出根因。

本模块是整个数据质量归因链路里最需要吃透机制的一环，重点有三：function calling 到底怎么跑起来、
模型如何收敛出结论、代码在哪些地方给 LLM 的开放性设了护栏。

## 一、tool_calling 机制原理与流程

**本质是原生 function calling，不是 prompt 里塞工具说明。** 工具对象在 tooling.py 定义
（tooling.py:7-41），经 to_openai_schema() 转成 JSON Schema（prompts.py:17-21），由模型侧
以 OpenAI 兼容协议透传（llm.py:73-99）。_diagnose_one 把 4 个调查工具（schema/lineage/cases/sql）
与 SUBMIT_DIAGNOSIS_SCHEMA 拼成同一个 tools 列表交给模型（diagnose.py:100）。

**重难点：submit_diagnosis 被伪装成「工具」。** 它并不是调查动作，而是「提交结论」这个出口，
schema 来自 Diagnosis.model_json_schema()（prompts.py:94-101）。这是用 function calling 实现
「强制结构化输出」的 trick：模型「调用一个函数」来交卷，参数结构就是 Diagnosis 字段（models.py:19-26），
天然满足 Pydantic 校验。

**消息协议：四角色成对回填。** 组装 system + user（diagnose.py:96-99）后进入循环，模型返回
tool_calls 时，必须回填一条 assistant 消息（diagnose.py:110），再为每条 tool_call 各回填一条
tool 消息（diagnose.py:136，用 tool_call_id 关联、content 是执行结果）。缺了 tool 消息，
下一轮模型看不到工具结果、无法继续。

**容错：工具失败不打断循环。** _run_tool 把工具异常捕获成字符串「tool error: ...」
（diagnose.py:79-84），参数 json.loads 失败兜底空 dict（diagnose.py:113-116），保证单个工具
出错不会让整条归因崩溃。

**对比 remediate.py：这里没有传 tool_choice。** 整改 Agent 用 tool_choice 强制每轮只返回
submit_remediation（remediate.py:133），但它是 Executor+Critic 修订循环；归因则是自由探索——
模型自主决定调哪些工具、调几次、何时交卷。这是「行动-观察工具循环」与「生成-评审修订循环」两种范式的分野。

## 二、归因收敛逻辑

收敛的核心矛盾：**结论得由模型给出，但代码不能任由模型跳过调查直接交卷、或编造证据。**
脚本用三道护栏卡住这两点。

1. **唯一正常出口 = submit_diagnosis。** 模型调它即宣告归因完成，参数是一份 Diagnosis：
   root_cause_category（枚举）、confidence（0~1）、evidence_chain、matched_cases（models.py:19-26）。

2. **证据闸门（防「空口结论」）。** evidence_chain 是脚本侧维护的 list（diagnose.py:101），记录每次
   真实工具调用（diagnose.py:135）。若模型一步没调查就想 submit_diagnosis，脚本拒绝这次提交
   （diagnose.py:118-122）并 continue 继续循环，逼它先调 lineage/cases/sql 收集证据。

3. **证据链以实际调用历史为准（防「编造证据」，最关键设计）。** 模型在 submit_diagnosis 参数里
   也会自述 evidence_chain 和 matched_cases，但脚本用 args.pop 直接丢弃（diagnose.py:126-127），
   改用脚本真实记录：evidence_chain 用实际工具调用历史、matched_cases 用 cases 工具真实命中的 ID
   （_matched_case_ids，diagnose.py:87-92；命中的 ID 由 tooling.py 的 cases_func 累积到
   tool.matched_case_ids）。一举两得：防模型声称查过却没查、命中却没命中；防自述字段与脚本传参
   关键字冲突抛 TypeError 被误降级成「未知」。

**三个降级出口**，最终都落回 Diagnosis("未知", confidence=0.0)：
- 模型空响应（既不调工具也不提交）→ break（diagnose.py:107-109）；
- submit_diagnosis 参数非法（Diagnosis(**args) 抛异常）→ 降级（diagnose.py:130-132）；
- 超过 max_steps（默认 5，见 make_diagnose_node 参数）仍不收敛 → 降级（diagnose.py:137-139），
  防无限循环、封预算上限。
降级不是报错，而是优雅降级：保证下游整改 Agent 永远拿到合法 Diagnosis，不被卡住。

## 三、逻辑边界剖析（它不做什么）

- 代码不判定根因对不对，只强制「走过证据流程 + 交出合法结构」；根因判断与置信度评分由 LLM 自评。
- matched_cases 只回填 cases 工具**实际命中**的案例 ID，不保证模型真的参考了这些案例得出结论——
  回填的是「检索到了什么」，不是「模型据此推理了什么」；两者之间的因果仍需看证据链和 trace。

## 四、整体流程串联（以重复键异常为例）

输入 type=duplicate, table=orders, column=order_id（由 build_diagnose_prompt 拼装，prompts.py:86-91）：
1. 组装 system + user（diagnose.py:96-99）；
2. 模型调 schema(orders) 收证据（tooling.py:31-33）；
3. 并行调 lineage(orders)（tooling.py:34-36）+ cases(...)（tooling.py:25-28）；
4. 调 submit_diagnosis(root_cause_category="脏数据注入", confidence=0.9)；
5. args.pop 丢弃自述的 evidence_chain/matched_cases，用真实证据链 + 真实命中 ID 构造 Diagnosis 返回（diagnose.py:126-129）。

设计哲学一句话：用 function calling 协议做「自由探索 + 结构化成卷」，再用「证据闸门 + 证据链/命中案例以实际为准
+ 预算封顶降级」三道护栏，把 LLM 的开放推理约束成一份可信、可审计、永不卡死的归因结论。
"""
import json

from dataquality_agent.models import Anomaly, Diagnosis, Evidence
from dataquality_agent.observability.tracing import trace_step
from dataquality_agent.prompts import (
    DIAGNOSE_SYSTEM_PROMPT,
    SUBMIT_DIAGNOSIS_SCHEMA,
    build_aggregate_diagnose_prompt,
    build_diagnose_prompt,
)


def _run_tool(tool, args: dict, tracer=None) -> str:
    """执行一个工具调用，异常也返回字符串（不打断循环）；有 tracer 时埋一个 tool span。"""
    if tracer is None:
        try:
            return str(tool.func(args))
        except Exception as e:
            return f"tool error: {e}"
    with tracer.span(f"tool:{tool.name}", input=str(args)) as span:
        try:
            result = str(tool.func(args))
        except Exception as e:
            result = f"tool error: {e}"
        span.output = result
        return result


def _matched_case_ids(tools: list) -> list[str]:
    """取 cases 工具真实命中的案例 ID（tools 里没有 cases 工具时返回空列表）。"""
    for t in tools:
        if t.name == "cases":
            return getattr(t, "matched_case_ids", [])
    return []


def _diagnose_one(anomaly: Anomaly, model, tools: list, max_steps: int) -> Diagnosis:
    messages = [
        {"role": "system", "content": DIAGNOSE_SYSTEM_PROMPT},
        {"role": "user", "content": build_diagnose_prompt(anomaly)},
    ]
    tool_schemas = [t.to_openai_schema() for t in tools] + [SUBMIT_DIAGNOSIS_SCHEMA]
    evidence_chain: list[str] = []
    tracer = getattr(model, "tracer", None)
    # 每次归因前清空 cases 命中缓存（tools 跨 anomaly 复用，避免上一个 anomaly 的命中串到这一个）
    _matched_case_ids(tools).clear()

    for _ in range(max_steps):
        resp = model.chat(messages, tools=tool_schemas)
        tool_calls = resp.get("tool_calls", [])
        if not tool_calls:
            break  # 模型既没调工具也没提交结论 → 降级 unknown
        messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls})
        for call in tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}
            if name == "submit_diagnosis":
                if not evidence_chain:
                    # 没调查就提交 → 拒绝，逼它先调工具收集证据
                    messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                     "content": "You have not called any investigation tool yet; submitting a conclusion is forbidden. Call lineage/cases/sql to collect evidence first."})
                    continue
                try:
                    # evidence_chain 以「实际工具调用历史」为准：丢弃模型自述的 evidence_chain（否则
                    # 重复传关键字会抛 TypeError 被误降级成「未知」）。matched_cases 同理，以 cases 工具真实命中为准。
                    args.pop("evidence_chain", None) # args存储了LLM在调用submit_diagnosis这个伪工具时自行生成并传入的所有参数
                    args.pop("matched_cases", None)
                    return Diagnosis(**args, evidence_chain=evidence_chain,
                                     matched_cases=list(_matched_case_ids(tools)))
                except Exception:
                    return Diagnosis(root_cause_category="unknown", confidence=0.0, evidence_chain=evidence_chain,
                                     matched_cases=list(_matched_case_ids(tools)))
            tool = next((t for t in tools if t.name == name), None)
            result = f"unknown tool: {name}" if tool is None else _run_tool(tool, args, tracer)
            evidence_chain.append(f"{name}({args}) -> {result}")
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result})
    # 超过 max_steps 仍不收敛 → 降级 unknown（防无限循环）
    return Diagnosis(root_cause_category="unknown", confidence=0.0, evidence_chain=evidence_chain,
                     matched_cases=list(_matched_case_ids(tools)))


def make_diagnose_node(model, tools: list, max_steps: int = 5):
    """返回归因节点函数。model/tools 通过闭包注入（model 需有 .chat；tools 为 Tool 列表）。"""
    tracer = getattr(model, "tracer", None)

    @trace_step(tracer, "node:diagnose")
    def diagnose(state):
        diagnoses = [_diagnose_one(a, model, tools, max_steps) for a in state.get("anomalies", [])]
        return {"diagnoses": diagnoses}
    return diagnose


def _aggregate_one(anomaly: Anomaly, finding: str, model) -> Diagnosis:
    """聚合诊断：把被指派的专职 Agent 的 finding 作为证据，调 submit_diagnosis 收敛成 Diagnosis。

    证据已由专职 Agent 收集，这里不再跑工具循环，只做「证据 → 结论」这一步。
    finding 可能含多行工具调用，按行拆成 evidence_chain（供轨迹评测解析）。
    """
    evidence = [l for l in finding.split("\n") if l] if finding else []
    resp = model.chat(
        [{"role": "user", "content": build_aggregate_diagnose_prompt(anomaly, evidence)}],
        tools=[SUBMIT_DIAGNOSIS_SCHEMA],
        tool_choice={"type": "function", "function": {"name": "submit_diagnosis"}},
    )
    for call in (resp or {}).get("tool_calls", []):
        if call.get("function", {}).get("name") == "submit_diagnosis":
            try:
                args = json.loads(call["function"]["arguments"])
                args.pop("evidence_chain", None)   # 丢弃自述，证据链以专职 Agent 的 finding 为准
                args.pop("matched_cases", None)
                return Diagnosis(**args, evidence_chain=evidence)
            except Exception:
                break
    return Diagnosis(root_cause_category="unknown", confidence=0.0, evidence_chain=evidence)


def make_aggregate_diagnose_node(model):
    """返回聚合诊断节点（§13 Supervisor 的 diagnose）：读 findings（每个异常一条）→ Diagnosis。"""
    tracer = getattr(model, "tracer", None)

    @trace_step(tracer, "node:diagnose")
    def diagnose(state):
        anomalies = state.get("anomalies", [])
        findings = state.get("findings", [])
        diagnoses = []
        for i, a in enumerate(anomalies):
            finding = findings[i] if i < len(findings) else ""
            diagnoses.append(_aggregate_one(a, finding, model))
        return {"diagnoses": diagnoses}
    return diagnose


def assemble_evidence(anomaly: Anomaly, adapter, lineage, retriever) -> list[str]:
    """确定性装配证据包：异常自身结构化证据 + 上游血缘 + 表 schema + 相似案例，全部无 LLM。

    「取证 vs 判定」分离的取证侧：这里只确定性取数，不下任何结论。每个来源单独 try/except，
    失败降级为「<source>: 不可用」，不让单个来源拖垮整包。
    """
    lines: list[str] = []
    ev = anomaly.evidence

    # 1. 异常自身证据（检测层已抓好的结构化 Evidence）
    parts: list[str] = []
    if ev.query:
        parts.append(f"query: {ev.query}")
    if ev.rows:
        parts.append(f"rows({len(ev.rows)}): {ev.rows[:3]}")  # 只带前 3 行样本，token-cheap
    if ev.expected:
        parts.append(f"expected: {ev.expected}")
    if ev.actual:
        parts.append(f"actual: {ev.actual}")
    if parts:
        lines.append("anomaly evidence: " + " | ".join(parts))

    # 2. 上游血缘
    try:
        ups = lineage.upstream(anomaly.table)
        if ups:
            lines.append(f"upstream lineage({anomaly.table}): {ups}")
    except Exception:
        lines.append("upstream lineage: unavailable")

    # 3. 表 schema
    try:
        schema = adapter.describe_table(anomaly.table)
        if schema:
            lines.append(f"schema({anomaly.table}): {schema}")
    except Exception:
        lines.append("schema: unavailable")

    # 4. 相似案例
    try:
        query = f"{anomaly.type} {anomaly.table} {anomaly.column or ''}".strip()
        cases = retriever.search(query, k=3)
        if cases:
            lines.append("similar cases: " + str(cases[:3]))
    except Exception:
        lines.append("similar cases: unavailable")

    return lines


def _thin_diagnose_one(anomaly: Anomaly, model, adapter, lineage, retriever) -> Diagnosis:
    """单一异常：装配证据包 → 单次 LLM 调用 → Diagnosis（带结构化 evidence）。

    证据包为空时直接降级「未知」，不浪费 LLM 调用（确定性优先）。
    """
    ev = anomaly.evidence
    # 裸结论（无 query/rows/expected/actual）→ 直接降级「未知」，不浪费 LLM 调用（判断皆有据）
    if not (ev.query or ev.rows or ev.expected or ev.actual):
        return Diagnosis(root_cause_category="unknown", confidence=0.0, evidence=[ev])
    evidence = assemble_evidence(anomaly, adapter, lineage, retriever)
    resp = model.chat(
        [{"role": "user", "content": build_aggregate_diagnose_prompt(anomaly, evidence)}],
        tools=[SUBMIT_DIAGNOSIS_SCHEMA],
        tool_choice={"type": "function", "function": {"name": "submit_diagnosis"}},
    )
    for call in (resp or {}).get("tool_calls", []):
        if call.get("function", {}).get("name") == "submit_diagnosis":
            try:
                args = json.loads(call["function"]["arguments"])
                args.pop("evidence_chain", None)   # 丢弃自述，证据链以脚本装配的为准
                args.pop("matched_cases", None)
                args.pop("evidence", None)         # 丢弃自述，结构化证据以 anomaly.evidence 为准
                return Diagnosis(**args, evidence_chain=evidence, evidence=[anomaly.evidence])
            except Exception:
                break
    return Diagnosis(root_cause_category="unknown", confidence=0.0, evidence_chain=evidence,
                     evidence=[anomaly.evidence])


def make_thin_diagnose_node(model, adapter, lineage, retriever):
    """返回薄归因节点：确定性装配证据包 + 单一 LLM 调用（不再跑工具循环、无分诊）。"""
    tracer = getattr(model, "tracer", None)

    @trace_step(tracer, "node:diagnose")
    def diagnose(state):
        anomalies = state.get("anomalies", [])
        diagnoses = [_thin_diagnose_one(a, model, adapter, lineage, retriever) for a in anomalies]
        return {"diagnoses": diagnoses}
    return diagnose
