"""声明式 L0 断言目录：YAML 声明（表+列+条件+阈值）→ 编译成带证据的 Detector。

「一切皆断言」里 declaration 那一半的落地——用户不 fork 代码就能声明自己的断言。
五种类型映射到 rules.py 的 check_* 参考实现，异常仍带结构化 Evidence。
"""
from dataclasses import dataclass
from pathlib import Path

import yaml


ASSERTION_TYPES = {"unique", "not_null", "null_rate", "value_range", "referential"}


@dataclass
class Assertion:
    """一条声明式断言（字段 = 声明字段；`min`/`max` 是 YAML 键，仅经 self 访问，无内置名遮蔽）。"""

    name: str
    type: str
    table: str | None = None
    column: str | None = None
    columns: list[str] | None = None
    max_rate: float | None = None
    where: str | None = None
    min: float | None = None
    max: float | None = None
    child_table: str | None = None
    child_column: str | None = None
    parent_table: str | None = None
    parent_column: str | None = None
    severity: str = "medium"


def _require(item: dict, key: str, name: str) -> str:
    v = item.get(key)
    if not v:
        raise ValueError(f"断言 {name} 缺少 {key}")
    return v


def load_assertions(path) -> list[Assertion]:
    """读 YAML、校验 schema（未知 type / 缺字段 / 值域非法 → fail-fast），返回断言列表。

    目录是用户自配的受信配置；`where` 是原始 SQL 片段（dbt 风格），不做 SQL 解析。
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "assertions" not in data:
        raise ValueError("assertions.yaml 需要顶层 'assertions' 列表")
    raw = data["assertions"]
    if not isinstance(raw, list):
        raise ValueError("'assertions' 必须是列表")

    assertions: list[Assertion] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"每条断言必须是映射，得到 {item!r}")
        name = item.get("name")
        if not name:
            raise ValueError("断言缺少 name")
        if name in seen:
            raise ValueError(f"断言 name 重复：{name}")
        seen.add(name)

        typ = item.get("type")
        if typ not in ASSERTION_TYPES:
            raise ValueError(f"未知断言类型：{typ}（允许：{sorted(ASSERTION_TYPES)}）")
        severity = item.get("severity", "medium")

        if typ == "unique":
            cols = item.get("columns")
            if not cols or not isinstance(cols, list):
                raise ValueError(f"unique 断言 {name} 需要非空 columns 列表")
            assertions.append(Assertion(name=name, type=typ, table=_require(item, "table", name),
                                        columns=cols, severity=severity))
        elif typ in ("not_null", "null_rate"):
            max_rate = item.get("max_rate")
            if typ == "null_rate" and max_rate is None:
                raise ValueError(f"null_rate 断言 {name} 需要 max_rate")
            assertions.append(Assertion(name=name, type=typ, table=_require(item, "table", name),
                                        column=_require(item, "column", name), max_rate=max_rate,
                                        where=item.get("where"), severity=severity))
        elif typ == "value_range":
            min_v, max_v = item.get("min"), item.get("max")
            if min_v is None and max_v is None:
                raise ValueError(f"value_range 断言 {name} 需要 min 或 max 至少一个")
            assertions.append(Assertion(name=name, type=typ, table=_require(item, "table", name),
                                        column=_require(item, "column", name),
                                        min=min_v, max=max_v, severity=severity))
        elif typ == "referential":
            child_column = _require(item, "child_column", name)
            assertions.append(Assertion(name=name, type=typ,
                                        child_table=_require(item, "child_table", name),
                                        child_column=child_column,
                                        parent_table=_require(item, "parent_table", name),
                                        parent_column=item.get("parent_column", child_column),
                                        severity=severity))
    return assertions
