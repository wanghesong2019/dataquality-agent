"""LLM-as-Judge 人工校准：跑 judge 打分 → 比人工标签 → 算一致率（证明 judge 靠谱）。

为什么需要：metrics.py 只能回答"对不对"（二元），judge 补"质量"维度，但 judge 本身有 bias/
随机性。所以配 judge_agreement 做人工抽检校准——人工标一批，比对 LLM 分 vs 人工分的一致率，
达标才敢信这个"法官"（judge.py 的 judge_agreement 就是这个用途，本脚本给它喂真数据跑出数字）。

用法：`python scripts/run_judge_calibration.py`（需 DEEPSEEK_API_KEY，或 .env）。
"""
from dataquality_agent.config import load_env
from dataquality_agent.eval.judge import Rubric, judge, judge_agreement
from dataquality_agent.llm import DeepSeekClient, LLMAdapter
from dataquality_agent.models import Anomaly, Diagnosis, Remediation

# 评分维度（rubric）：整改方案质量的三个可判定面。description 里写清 1~5 分锚点，
# 让 judge 和人工用同一把尺子（否则"5 分"的含义各自脑补，一致率必然低）。
RUBRIC = Rubric(
    dimensions=["action_type", "方案能修根因", "risk_level"],
    description=(
        "整改方案质量，逐维度 1~5 分（5=最好）："
        "① action_type：可逆类（重复/负值/空值）能用 SQL 修却开 ticket/alert=1，用 fix_sql=5；"
        "数据丢失类（孤儿外键/上游删行）该 ticket 重跑上游，却用 fix_sql 删孤儿行=1；"
        "② 方案能修根因：SQL 语义错误/跑偏/空占位=1，能正确消除该异常=5；"
        "③ risk_level：涉及 DELETE/UPDATE/金额字段却标 low=1，正确标 high=5"
    ),
)


# 校准集：每条 = (异常, 根因 Diagnosis, 整改方案, 人工标签 {维度: 1~5})。
# 把 Diagnosis 作为 context 喂给 judge——否则"方案能否修根因"是无源之水（judge 不知道根因）。
SAMPLES = [
    # 1. 重复主键 → 脏数据注入 → 正确去重 fix_sql + 标 high
    (Anomaly(type="duplicate", table="orders", column="order_id"),
     Diagnosis(root_cause_category="脏数据注入", confidence=0.9),
     Remediation(action_type="fix_sql", risk_level="high",
                 sql_or_suggestion="DELETE FROM orders WHERE rowid NOT IN (SELECT MIN(rowid) FROM orders GROUP BY order_id)"),
     {"action_type": 5, "方案能修根因": 5, "risk_level": 5}),

    # 2. 负价格 → 脏数据注入 → fix_sql 回填 + 标 high（金额字段）
    (Anomaly(type="value_range", table="order_items", column="price"),
     Diagnosis(root_cause_category="脏数据注入", confidence=0.9),
     Remediation(action_type="fix_sql", risk_level="high",
                 sql_or_suggestion="UPDATE order_items SET price = 0 WHERE price < 0"),
     {"action_type": 5, "方案能修根因": 4, "risk_level": 5}),

    # 3. 孤儿外键 → 上游任务失败（数据丢失）→ 错误地给了 fix_sql 删孤儿行（应 ticket 重跑上游）
    (Anomaly(type="orphan", table="order_items", column="order_id"),
     Diagnosis(root_cause_category="上游任务失败", confidence=0.8),
     Remediation(action_type="fix_sql", risk_level="high",
                 sql_or_suggestion="DELETE FROM order_items WHERE order_id NOT IN (SELECT order_id FROM orders)"),
     {"action_type": 1, "方案能修根因": 1, "risk_level": 3}),

    # 4. 空值 → 脏数据注入 → fix_sql 回填 + 标 medium
    (Anomaly(type="null_rate", table="orders", column="order_delivered_customer_date"),
     Diagnosis(root_cause_category="脏数据注入", confidence=0.9),
     Remediation(action_type="fix_sql", risk_level="medium",
                 sql_or_suggestion="UPDATE orders SET order_delivered_customer_date = order_estimated_delivery_date WHERE order_status='delivered' AND order_delivered_customer_date IS NULL"),
     {"action_type": 5, "方案能修根因": 4, "risk_level": 5}),

    # 5. 重复 → 脏数据注入 → 错误 action_type（明明能 SQL 去重却开 ticket）
    (Anomaly(type="duplicate", table="orders", column="order_id"),
     Diagnosis(root_cause_category="脏数据注入", confidence=0.9),
     Remediation(action_type="ticket", risk_level="low",
                 sql_or_suggestion="请人工排查重复订单"),
     {"action_type": 1, "方案能修根因": 1, "risk_level": 3}),

    # 6. 负价格 → 脏数据注入 → fix_sql 但 WHERE 缺失（危险：改全表）且没标 high
    (Anomaly(type="value_range", table="order_items", column="price"),
     Diagnosis(root_cause_category="脏数据注入", confidence=0.9),
     Remediation(action_type="fix_sql", risk_level="low",
                 sql_or_suggestion="UPDATE order_items SET price = 0"),
     {"action_type": 4, "方案能修根因": 1, "risk_level": 1}),
]


def main() -> None:
    load_env(".env")
    model = LLMAdapter(DeepSeekClient())
    scores = [judge(model, a, r, RUBRIC, context=d).scores for a, d, r, _ in SAMPLES]
    labels = [label for _, _, _, label in SAMPLES]
    exact = judge_agreement(scores, labels)
    tol1 = judge_agreement(scores, labels, tolerance=1)

    print(f"样本数 = {len(SAMPLES)}")
    print(f"judge_agreement：exact = {exact:.2%}，±1 容差 = {tol1:.2%}")
    for i, (s, l) in enumerate(zip(scores, labels), 1):
        print(f"  #{i} judge={s} 人工={l}")


if __name__ == "__main__":
    main()
