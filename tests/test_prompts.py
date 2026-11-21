"""prompts.py 的 schema 瘦身门禁：function calling 只让模型输出「它决定的字段」。

证据字段（evidence / evidence_chain / matched_cases）由代码侧从真实证据装配（判断皆有据），
若塞进 function calling 的 schema，模型会把整包证据复述一遍、撑爆 completion token
（实测 thin 诊断单 call 从 ~百 token 飙到 ~3.3 万 token）。此测试防回归。
"""
from dataquality_agent.prompts import SUBMIT_DIAGNOSIS_SCHEMA, SUBMIT_REMEDIATION_SCHEMA


def _props(schema):
    return schema["function"]["parameters"]["properties"]


def test_submit_diagnosis_schema_is_lean():
    """submit_diagnosis 只让模型输出 root_cause_category + confidence；证据代码侧填。"""
    assert set(_props(SUBMIT_DIAGNOSIS_SCHEMA)) == {"root_cause_category", "confidence"}


def test_submit_remediation_schema_is_lean():
    """submit_remediation 只让模型输出 action_type/sql_or_suggestion/risk_level；evidence 代码侧填。"""
    assert set(_props(SUBMIT_REMEDIATION_SCHEMA)) == {
        "action_type", "sql_or_suggestion", "risk_level",
    }
