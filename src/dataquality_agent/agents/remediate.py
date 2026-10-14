"""整改 Agent（Executor + Critic 自评审）：生成修复方案，模型输出里带风险等级。"""
import json

from dataquality_agent.models import Diagnosis, Remediation


def make_remediate_node(model):
    """返回整改节点函数。model 通过闭包注入。"""
    def remediate(state):
        remediations = []
        for d in state.get("diagnoses", []):
            # TODO(M3/M4)：同 diagnose——改用结构化输出（Pydantic→JSON Schema 强制）替换手写 JSON schema。
            prompt = (
                f"根因：{d.root_cause_category}（置信度 {d.confidence}）。给出修复方案。"
                '输出 JSON，字段必须为：{"action_type": "fix_sql/add_rule/ticket/alert", '
                '"sql_or_suggestion": "字符串", "risk_level": "low/medium/high"}。'
                'action_type 含义：fix_sql=修复SQL、add_rule=新增质量规则、ticket=生成工单、alert=告警通知。'
                'risk_level 判定：涉及 DELETE/UPDATE 生产表、金额字段、权限变更→high；只读建议→low；其余→medium。'
            )
            resp = model(prompt).strip()
            try:
                data = json.loads(resp)
            except json.JSONDecodeError:
                data = {}
            remediations.append(Remediation(
                action_type=data.get("action_type", "ticket"),
                sql_or_suggestion=data.get("sql_or_suggestion", ""),
                risk_level=data.get("risk_level", "low"),
            ))
        return {"remediations": remediations}
    return remediate
