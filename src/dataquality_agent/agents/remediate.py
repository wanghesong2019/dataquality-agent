"""整改 Agent（Executor + Critic 自评审）：用 function calling 结构化产出修复方案。

两句表述拆成两半
----------------
①「强制 submit_remediation 结构化输出」——靠 function calling：不给模型自由文本的余地，
逼它只能"调用" submit_remediation 这个工具，工具参数就是修复方案的结构字段。

②「风险分级」——靠 Remediation.requires_approval 这个派生属性，把 risk_level == "high"
翻译成"需要人工审批"，下游据此分流。

两行代码的含义：能力边界定义 vs 执行策略控制
--------------------------------------------
这两行是 Tool Calling 机制里两个不同层面的约束——一个管「参数长什么样」，一个管「要不要调用」。

一、tools=[SUBMIT_REMEDIATION_SCHEMA] —— 能力边界定义（结构化输出的语法约束）
SUBMIT_REMEDIATION_SCHEMA 定义在 prompts.py，其中 parameters = Remediation.model_json_schema()
把 Pydantic 的 4 个字段（action_type / sql_or_suggestion / risk_level / anomaly_id，models.py）自动
转成 JSON Schema——"你有一个工具叫 submit_remediation，调用它必须填这 4 个字段"。它只解决
"输出格式对不对"，背后三层原理：
1. 上下文注入：Schema 被序列化成 JSON Schema 拼进系统消息，模型生成时把它当"必须遵守的语法规则"。
2. 受控解码（核心）：现代推理引擎（vLLM/SGLang/llama.cpp）支持基于 JSON Schema 的约束采样——
   每生成一个 Token，引擎根据已生成的 JSON 结构 + 预定义 Schema 动态计算下一个合法 Token 的
   概率掩码，非法 Token 概率强制置 0，在解码层面保证输出 100% 符合 Schema（不是事后校验）。
3. 后处理兜底：引擎不支持受控解码或模型突破约束时，服务端做 JSON 解析 + Schema 验证，失败则
   重试/报错/返回默认——这是防御性兜底，不是首选。

二、tool_choice={"type": "function", "function": {"name": "submit_remediation"}} —— 执行策略控制（行为模式的强制路由）
它强制模型唯一输出 submit_remediation——"只能用这个工具，不能回纯文本、不能调别的工具、也不能
选择不调"。它只解决"要不要调用、调用谁"，与 Schema 无关，背后三点：
1. 系统指令覆盖：API 内部把默认的 auto（模型自主判断）替换成强制指令——"你必须调用
   submit_remediation，不得直接回复文本"。
2. Logit Bias / Token Masking：推理引擎对 submit_remediation 相关 Token 施加极大正 bias（几乎
   必选），同时压低普通文本 Token 的概率，防止模型"跳过"工具直接聊天。
3. 绕过意图识别：auto 模式下模型要先做"是否需要工具"的分类；tool_choice 指定后直接跳过这一步，
   把工具调用变成唯一合法输出路径——本质是把开放式生成降级成受限的槽位填充。

一句话：tools 管"输出格式对不对"（能力边界），tool_choice 管"要不要调用、调用谁"（执行策略），
两者正交——即使 Schema 有误，只要 tool_choice 指定了函数名，模型仍会尝试调用（只是参数可能不合法）。

数据流串起来
------------
model.chat(messages, tools=[schema], tool_choice={...})（remediate.py:131-135）
→ 返回 {content, tool_calls}（llm.py:88）
→ _parse_remediation(resp)（remediate.py:61-71）遍历 tool_calls 找 submit_remediation
→ json.loads(arguments) → Remediation(**args) 做 Pydantic 校验；失败返回 None，
由 _remediate_one 降级 Remediation(action_type="ticket", sql_or_suggestion="", risk_level="low")（remediate.py:139）。

风险分级 requires_approval（models.py:37-40）
--------------------------------------------
@property 派生而非存储字段，三个点：

1. 派生属性是"单一真相源"：risk_level 是唯一事实，requires_approval 由它算出，不可能
   出现 risk_level="high" 但 requires_approval=False 的两字段打架 bug。
2. risk_level 由模型按 prompt 规则填（prompts.py:35）：涉及 DELETE/UPDATE 生产表、金额
   字段、权限变更 → high。
3. 下游两处消费：graph.py:7-11 的 _route() 用 any(requires_approval) 决定走 approve 还是
   report；hitl.py:42 只把高危方案喂给 interrupt() 暂停等人。

一句话：模型填 risk_level → requires_approval 派生布尔 → _route 决定要不要人工拦一道
→ hitl 只拦高危。
"""
import json
import re

from dataquality_agent.models import CriticVerdict, Remediation
from dataquality_agent.observability.tracing import trace_step
from dataquality_agent.prompts import (
    SUBMIT_CRITIQUE_SCHEMA,
    SUBMIT_REMEDIATION_SCHEMA,
    build_critic_prompt,
    build_remediate_prompt,
)


def _parse_remediation(resp: dict) -> Remediation | None:
    """从 assistant message 取 submit_remediation 参数；解析/校验失败返回 None（调用方降级 ticket/low）。"""
    for call in resp.get("tool_calls", []):
        if call.get("function", {}).get("name") != "submit_remediation":
            continue
        try:
            args = json.loads(call["function"]["arguments"])
            return Remediation(**args)
        except Exception:
            return None
    return None


def _parse_critic(resp: dict) -> CriticVerdict:
    """从 Critic 的 assistant message 取 submit_critique 参数；解析失败降级为「不通过」（fail-closed）。"""
    for call in resp.get("tool_calls", []):
        if call.get("function", {}).get("name") != "submit_critique":
            continue
        try:
            args = json.loads(call["function"]["arguments"])
            return CriticVerdict(**args)
        except Exception:
            break
    return CriticVerdict(passed=False, feedback="评审结论无法解析")


def _extract_tables(sql: str) -> set[str]:
    """正则抽取 SQL 里 from/join/update/into 后的表名（启发式，非真解析器，生产换 sqlglot）。"""
    return set(re.findall(r"\b(?:from|join|update|into)\s+([a-zA-Z_]\w*)", sql, re.IGNORECASE))


def _rule_check(candidate: Remediation, whitelist: set[str]) -> list[str]:
    """确定性规则闸门：只查可被硬判定的错误（SQL 危险 / 表不存在 / 高危漏标），能定论的不交给 LLM。"""
    failures = []
    if candidate.action_type == "fix_sql":
        sql = candidate.sql_or_suggestion
        if re.search(r"\b(delete|update|drop|truncate)\b", sql, re.IGNORECASE) and \
                not re.search(r"\bwhere\b", sql, re.IGNORECASE):
            failures.append("写操作(DELETE/UPDATE/DROP/TRUNCATE)缺少 WHERE 条件")
        for t in _extract_tables(sql):
            if t not in whitelist:
                failures.append(f"SQL 引用了不存在的表 {t}")
        if re.search(r"\b(delete|update)\b", sql, re.IGNORECASE) and candidate.risk_level != "high":
            failures.append("含 DELETE/UPDATE 的写操作 risk_level 必须为 high")
    return failures


def _llm_critic(candidate: Remediation, anomaly, diagnosis, model) -> CriticVerdict:
    """LLM 语义评审：只判规则查不了的软问题（action_type 归类、建议是否对得上根因、risk_level 语义）。"""
    resp = model.chat(
        [{"role": "user", "content": build_critic_prompt(anomaly, diagnosis, candidate)}],
        tools=[SUBMIT_CRITIQUE_SCHEMA],
        tool_choice={"type": "function", "function": {"name": "submit_critique"}},
    )
    return _parse_critic(resp)


def _review_once(candidate: Remediation, anomaly, diagnosis, model, whitelist) -> CriticVerdict:
    """两级评审：规则闸门先跑（能定论的不花 LLM），规则通过才交给 LLM 判语义。"""
    rule_failures = _rule_check(candidate, whitelist)
    if rule_failures:
        return CriticVerdict(passed=False, feedback="；".join(rule_failures))
    return _llm_critic(candidate, anomaly, diagnosis, model)


def _remediate_one(anomaly, diagnosis, model, whitelist, max_rounds: int = 3) -> Remediation:
    """Executor + Critic 修订循环：生成 → 评审 → 不合格带反馈打回重写；超限强制 high 交人工。"""
    messages = [{"role": "user", "content": build_remediate_prompt(anomaly, diagnosis)}]
    candidate = Remediation(action_type="ticket", sql_or_suggestion="", risk_level="low")
    for _ in range(max_rounds):
        resp = model.chat(
            messages,
            tools=[SUBMIT_REMEDIATION_SCHEMA], #定义模型输出的结构约束(Schema),API服务端会据此Schema对模型的输出进行约束或后处理校验
            tool_choice={"type": "function", "function": {"name": "submit_remediation"}}, #强制指定模型唯一的输出动作，剥夺模型"是否调用工具"及"调用哪个工具"的自由度
        )
        candidate = _parse_remediation(resp)
        if candidate is None:
            # 解析失败 → 降级 ticket/low，终止（没有可评审的方案）
            return Remediation(action_type="ticket", sql_or_suggestion="", risk_level="low")
        verdict = _review_once(candidate, anomaly, diagnosis, model, whitelist)
        if verdict.passed:
            return candidate
        # 不合格：把 Critic 反馈当作「工具结果」回填，逼 Executor 按反馈重写
        messages.append({"role": "assistant", "content": "", "tool_calls": resp.get("tool_calls", [])})
        for call in resp.get("tool_calls", []):
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": verdict.feedback})
    # 超 max_rounds 仍不合格 → fail-safe：强制 high，走人工审批，绝不静默放行
    return candidate.model_copy(update={"risk_level": "high"})


def make_remediate_node(model, adapter, max_rounds: int = 3):
    """返回整改节点函数。model 通过闭包注入（需有 .chat）；adapter 用于规则闸门的表白名单。

    Executor 生成方案 → 规则闸门(确定性) + Critic(LLM 语义) 评审，不合格带反馈打回重写；
    超 max_rounds 仍不合格则强制 high 交人工（fail-safe）。
    """
    whitelist = set(adapter.list_tables())
    tracer = getattr(model, "tracer", None)

    @trace_step(tracer, "node:remediate")
    def remediate(state):
        remediations = [
            _remediate_one(a, d, model, whitelist, max_rounds)
            for a, d in zip(state.get("anomalies", []), state.get("diagnoses", []))
        ]
        return {"remediations": remediations}
    return remediate
