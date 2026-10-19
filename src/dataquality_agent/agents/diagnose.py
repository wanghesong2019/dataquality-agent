"""归因 Agent：原生 function calling 工具循环，查血缘/案例/SQL → 收敛出根因。

本模块是整个数据质量归因链路里最需要吃透机制的一环，重点有三：function calling 到底怎么跑起来、
模型如何收敛出结论、代码在哪些地方给 LLM 的开放性设了护栏。

## 一、tool_calling 机制原理与流程

**本质是原生 function calling，不是 prompt 里塞工具说明。** 工具对象在 tooling.py 定义
（tooling.py:7-27），经 to_openai_schema() 转成 JSON Schema（prompts.py:17-21），由模型侧
以 OpenAI 兼容协议透传（llm.py:67-88）。_diagnose_one 把 4 个调查工具（schema/lineage/cases/sql）
与 SUBMIT_DIAGNOSIS_SCHEMA 拼成同一个 tools 列表交给模型（diagnose.py:92）。

**重难点：submit_diagnosis 被伪装成「工具」。** 它并不是调查动作，而是「提交结论」这个出口，
schema 来自 Diagnosis.model_json_schema()（prompts.py:71-78）。这是用 function calling 实现
「强制结构化输出」的 trick：模型「调用一个函数」来交卷，参数结构就是 Diagnosis 字段（models.py:19-26），
天然满足 Pydantic 校验。

**消息协议：四角色成对回填。** 组装 system + user（diagnose.py:88-91）后进入循环，模型返回
tool_calls 时，必须回填一条 assistant 消息（diagnose.py:100），再为每条 tool_call 各回填一条
tool 消息（diagnose.py:123，用 tool_call_id 关联、content 是执行结果）。缺了 tool 消息，
下一轮模型看不到工具结果、无法继续。

**容错：工具失败不打断循环。** _run_tool 把工具异常捕获成字符串「tool error: ...」
（diagnose.py:79-84），参数 json.loads 失败兜底空 dict（diagnose.py:103-106），保证单个工具
出错不会让整条归因崩溃。

**对比 remediate.py：这里没有传 tool_choice。** 整改 Agent 用 tool_choice 强制只返回
submit_remediation（remediate.py:31-35，一枪定音），归因则是自由探索——模型自主决定调哪些工具、
调几次、何时交卷。这也是「多步证据收敛」与「单步结构化产出」两种范式在实现上的分野。

## 二、归因收敛逻辑

收敛的核心矛盾：**结论得由模型给出，但代码不能任由模型跳过调查直接交卷、或编造证据。**
脚本用三道护栏卡住这两点。

1. **唯一正常出口 = submit_diagnosis。** 模型调它即宣告归因完成，参数是一份 Diagnosis：
   root_cause_category（枚举）、confidence（0~1）、evidence_chain、matched_cases（models.py:19-26）。

2. **证据闸门（防「空口结论」）。** evidence_chain 是脚本侧维护的 list（diagnose.py:93），记录每次
   真实工具调用（diagnose.py:122）。若模型一步没调查就想 submit_diagnosis，脚本拒绝这次提交
   （diagnose.py:108-112）并 continue 继续循环，逼它先调 lineage/cases/sql 收集证据。

3. **证据链以实际调用历史为准（防「编造证据」，最关键设计）。** 模型在 submit_diagnosis 参数里
   也会自述一份 evidence_chain，但脚本用 args.pop("evidence_chain") 直接丢弃（diagnose.py:116），
   改用脚本真实记录的 evidence_chain。一举两得：防模型声称查过却没查；防自述字段与脚本传参关键字
   冲突抛 TypeError 被误降级成「未知」（diagnose.py:114-115）。

**三个降级出口**，最终都落回 Diagnosis("未知", confidence=0.0)：
- 模型空响应（既不调工具也不提交）→ break（diagnose.py:97-99）；
- submit_diagnosis 参数非法（Diagnosis(**args) 抛异常）→ 降级（diagnose.py:118-119）；
- 超过 max_steps（默认 5，见 make_diagnose_node 参数）仍不收敛 → 降级（diagnose.py:124-125），
  防无限循环、封预算上限。
降级不是报错，而是优雅降级：保证下游整改 Agent 永远拿到合法 Diagnosis，不被卡住。

## 三、逻辑边界剖析（它不做什么）

- 代码不判定根因对不对，只强制「走过证据流程 + 交出合法结构」；根因判断与置信度评分由 LLM 自评。
- matched_cases 字段模型自填、代码不回填（返回时只覆盖 evidence_chain，diagnose.py:116-117）；
  若模型没调 cases 却乱填 matched_cases，证据闸门拦不住（闸门只查 evidence_chain 非空）。

## 四、整体流程串联（以重复键异常为例）

输入 type=duplicate, table=orders, column=order_id（由 build_diagnose_prompt 拼装，prompts.py:63-68）：
1. 组装 system + user（diagnose.py:88-91）；
2. 模型调 schema(orders) 收证据（tooling.py:15-17）；
3. 并行调 lineage(orders)（tooling.py:18-20）+ cases(...)（tooling.py:21-23）；
4. 调 submit_diagnosis(root_cause_category="脏数据注入", confidence=0.9, matched_cases=["dup_orders"])；
5. args.pop("evidence_chain") 丢弃自述、用真实证据链构造 Diagnosis 返回（diagnose.py:116-117）。

设计哲学一句话：用 function calling 协议做「自由探索 + 结构化成卷」，再用「证据闸门 + 证据链以实际为准
+ 预算封顶降级」三道护栏，把 LLM 的开放推理约束成一份可信、可审计、永不卡死的归因结论。
"""
import json

from dataquality_agent.models import Anomaly, Diagnosis
from dataquality_agent.prompts import DIAGNOSE_SYSTEM_PROMPT, SUBMIT_DIAGNOSIS_SCHEMA, build_diagnose_prompt


def _run_tool(tool, args: dict) -> str:
    """执行一个工具调用，异常也返回字符串（不打断循环）。"""
    try:
        return str(tool.func(args))
    except Exception as e:
        return f"tool error: {e}"


def _diagnose_one(anomaly: Anomaly, model, tools: list, max_steps: int) -> Diagnosis:
    messages = [
        {"role": "system", "content": DIAGNOSE_SYSTEM_PROMPT},
        {"role": "user", "content": build_diagnose_prompt(anomaly)},
    ]
    tool_schemas = [t.to_openai_schema() for t in tools] + [SUBMIT_DIAGNOSIS_SCHEMA]
    evidence_chain: list[str] = []

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
                                     "content": "你还没调用任何调查工具，禁止提交结论。请先调用 lineage/cases/sql 收集证据。"})
                    continue
                try:
                    # evidence_chain 以「实际工具调用历史」为准：丢弃模型自述的 evidence_chain（否则
                    # 重复传关键字会抛 TypeError 被误降级成「未知」）
                    args.pop("evidence_chain", None)
                    return Diagnosis(**args, evidence_chain=evidence_chain)
                except Exception:
                    return Diagnosis(root_cause_category="未知", confidence=0.0, evidence_chain=evidence_chain)
            tool = next((t for t in tools if t.name == name), None)
            result = f"unknown tool: {name}" if tool is None else _run_tool(tool, args)
            evidence_chain.append(f"{name}({args}) -> {result}")
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result})
    # 超过 max_steps 仍不收敛 → 降级 unknown（防无限循环）
    return Diagnosis(root_cause_category="未知", confidence=0.0, evidence_chain=evidence_chain)


def make_diagnose_node(model, tools: list, max_steps: int = 5):
    """返回归因节点函数。model/tools 通过闭包注入（model 需有 .chat；tools 为 Tool 列表）。"""
    def diagnose(state):
        diagnoses = [_diagnose_one(a, model, tools, max_steps) for a in state.get("anomalies", [])]
        return {"diagnoses": diagnoses}
    return diagnose
