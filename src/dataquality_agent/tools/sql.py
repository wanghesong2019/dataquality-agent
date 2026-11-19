"""SQL 只读执行器（安全护栏：只读、禁多语句、表白名单、行数上限）。"""
import re


class SQLGuardError(Exception):
    """SQL 护栏违规。"""


def validate_sql(sql: str, whitelist: set[str]) -> str:
    """校验 SQL：只读 + 禁多语句 + 表白名单。返回空串表示合法，否则返回错误信息。"""
    s = sql.strip()
    if not s.lower().startswith("select"):
        return "only SELECT is allowed"
    # 去掉末尾分号后若还有分号 → 多语句
    if s.rstrip().rstrip(";").count(";") > 0:
        return "multi-statement is not allowed"
    tables = re.findall(r"\b(?:from|join)\s+([a-zA-Z_]\w*)", s, re.IGNORECASE)
    for t in tables:
        if t not in whitelist:
            return f"table not in whitelist: {t}"
    return ""


class SafeSQL:
    """Agent 唯一允许使用的 SQL 执行入口——所有 SQL 都经过护栏校验。"""

    def __init__(self, adapter, whitelist: set[str], max_rows: int = 10000):
        self.adapter = adapter
        self.whitelist = whitelist
        self.max_rows = max_rows

    def run(self, sql: str) -> list[tuple]:
        err = validate_sql(sql, self.whitelist)
        if err:
            raise SQLGuardError(err)
        rows = self.adapter.execute(sql)
        if len(rows) > self.max_rows:
            raise SQLGuardError(f"result exceeds max_rows ({self.max_rows})")
        return rows
