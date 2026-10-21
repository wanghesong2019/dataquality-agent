"""整改 Agent（Executor + Critic 自评审）：用 function calling 结构化产出修复方案。

两句表述拆成两半
----------------
①「强制 submit_remediation 结构化输出」——靠 function calling：不给模型自由文本的余地，
逼它只能"调用" submit_remediation 这个工具，工具参数就是修复方案的结构字段。

②「风险分级」——靠 Remediation.requires_approval 这个派生属性，把 risk_level == "high"
翻译成"需要人工审批"，下游据此分流。

两行代码的含义
--------------
tools=[SUBMIT_REMEDIATION_SCHEMA] —— 告诉模型"你有这个工具"。SUBMIT_REMEDIATION_SCHEMA
定义在 prompts.py:42-49，其中 parameters = Remediation.model_json_schema()（prompts.py:47）
把 Pydantic 模型 Remediation 的四个字段（action_type / sql_or_suggestion / risk_level /
anomaly_id，models.py:29-35）自动转成 JSON Schema。所以这一行在说："你有一个工具叫
submit_remediation，要调用它就必须填这 4 个字段。" 模型看到 schema 后，输出不再是自由
文本，而是被约束成这组命名字段——这就是"结构化"的来源。

tool_choice={"type": "function", "function": {"name": "submit_remediation"}} —— 逼模型
"只能用这个工具"。这是 OpenAI 兼容协议里的强制选工具语法：模型只能调用
submit_remediation，不能回纯文本、不能调别的工具、也不能选择不调。没有这行时，模型
可能回一句自然语言；有了这行，返回的 tool_calls 里必定是 submit_remediation。这就是
"强制"的落点。

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


def make_remediate_node(model, conn, max_rounds: int = 3):
    """返回整改节点函数。model 通过闭包注入（需有 .chat）；conn 用于规则闸门的表白名单。

    Executor 生成方案 → 规则闸门(确定性) + Critic(LLM 语义) 评审，不合格带反馈打回重写；
    超 max_rounds 仍不合格则强制 high 交人工（fail-safe）。
    """
    whitelist = {t[0] for t in conn.execute("SHOW TABLES").fetchall()}
    tracer = getattr(model, "tracer", None)

    @trace_step(tracer, "node:remediate")
    def remediate(state):
        remediations = [
            _remediate_one(a, d, model, whitelist, max_rounds)
            for a, d in zip(state.get("anomalies", []), state.get("diagnoses", []))
        ]
        return {"remediations": remediations}
    return remediate
