"""把巡检 state 渲染成人类可读的英文文本报告（stdout 用）。"""
import datetime as dt


def _fmt(value):
    """把嵌套结构里的 datetime/date 转成干净的 ISO 字符串（供 rows 预览）。"""
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat(sep=" ")
    if isinstance(value, dict):
        return {k: _fmt(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_fmt(v) for v in value]
    return value


def format_run_report(state: dict) -> str:
    """把序列化的巡检 state（runtime.get 返回的 dict）渲染成文本报告。

    纯函数：无 I/O、不改输入。anomalies / diagnoses / remediations 按下标对齐（zip 截断）。
    报告摘要（report.summary）无论是否有异常都追加在末尾。
    """
    anomalies = state.get("anomalies") or []
    diagnoses = state.get("diagnoses") or []
    remediations = state.get("remediations") or []
    report = state.get("report")

    lines: list[str] = []
    if not anomalies:
        lines.append("No anomalies detected")
    else:
        for i, anomaly in enumerate(anomalies):
            diag = diagnoses[i] if i < len(diagnoses) else None
            rem = remediations[i] if i < len(remediations) else None

            typ = anomaly.get("type") or "?"
            table = anomaly.get("table") or "?"
            column = anomaly.get("column") or ""
            severity = anomaly.get("severity") or "medium"
            where = f"{table}.{column}" if column else table
            lines.append(f"[{i + 1}] {typ}  {where}  (severity={severity})")

            ev = anomaly.get("evidence") or {}
            lines.append(f"    expected: {ev.get('expected') or '—'}")
            lines.append(f"    actual:   {ev.get('actual') or '—'}")
            rows = ev.get("rows")
            if rows:
                lines.append(f"    rows: {_fmt(rows[:3])}")

            if diag:
                cat = diag.get("root_cause_category") or "unknown"
                conf = diag.get("confidence")
                conf_s = f" (confidence {conf})" if conf is not None else ""
                lines.append(f"    root cause: {cat}{conf_s}")

            if rem:
                action = rem.get("action_type") or "?"
                sql = rem.get("sql_or_suggestion") or ""
                risk = rem.get("risk_level") or "low"
                needs = ", requires approval" if risk == "high" else ""
                lines.append(f"    remediation: [{action}] {sql} (risk={risk}{needs})")

        n = len(anomalies)
        high = sum(1 for r in remediations if (r or {}).get("risk_level") == "high")
        footer = f"{n} {'anomaly' if n == 1 else 'anomalies'} total"
        if high:
            footer += f", {high} high-risk {'remediation' if high == 1 else 'remediations'} awaiting approval"
        lines.append(footer)

    if report and report.get("summary"):
        lines.append(str(report["summary"]))

    return "\n".join(lines)
