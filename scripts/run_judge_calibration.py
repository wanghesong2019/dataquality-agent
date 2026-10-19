"""LLM-as-Judge 人工校准：跑 judge 打分 → 比人工标签 → 算一致率（证明 judge 靠谱）。

为什么需要：metrics.py 只能回答"对不对"（二元），judge 补"质量"维度，但 judge 本身有 bias/
随机性。所以配 judge_agreement 做人工抽检校准——人工标一批，比对 LLM 分 vs 人工分的一致率，
达标才敢信这个"法官"（judge.py 的 judge_agreement 就是这个用途，本脚本给它喂真数据跑出数字）。

用法：`python scripts/run_judge_calibration.py`（需 DEEPSEEK_API_KEY，或 .env）。
"""
from dataquality_agent.config import load_env
from dataquality_agent.eval.judge import Rubric, judge, judge_agreement
from dataquality_agent.llm import DeepSeekClient, LLMAdapter
from dataquality_agent.models import Anomaly, Remediation

# 评分维度（rubric）：整改方案质量的三个可判定面
RUBRIC = Rubric(
    dimensions=["action_type 归类", "方案能修根因", "risk_level 判断"],
    description="整改方案质量（action_type 是否合理、方案能否修掉根因、风险等级是否判准）",
)


# 校准集：每条 = (异常, 整改方案, 人工标签 {维度: 1~5})。
# 刻意混入「好方案」和「坏方案」，否则全是满分测不出 judge 的区分力。
SAMPLES = [
    # 1. 重复主键 → 正确的 fix_sql + 正确标 high（写操作）
    (Anomaly(type="duplicate", table="orders", column="order_id"),
     Remediation(action_type="fix_sql", risk_level="high",
                 sql_or_suggestion="DELETE FROM orders WHERE order_id IN (SELECT order_id FROM orders GROUP BY order_id HAVING COUNT(*)>1)"),
     {"action_type 归类": 5, "方案能修根因": 5, "risk_level 判断": 5}),

    # 2. 负价格 → 正确 fix_sql 回填 + 正确标 high（金额字段）
    (Anomaly(type="value_range", table="order_items", column="price"),
     Remediation(action_type="fix_sql", risk_level="high",
                 sql_or_suggestion="UPDATE order_items SET price = 0 WHERE price < 0"),
     {"action_type 归类": 5, "方案能修根因": 4, "risk_level 判断": 5}),

    # 3. 孤儿外键 → 错误地给了 fix_sql（数据已在上游丢失，应 ticket 重跑上游）
    (Anomaly(type="orphan", table="order_items", column="order_id"),
     Remediation(action_type="fix_sql", risk_level="high",
                 sql_or_suggestion="DELETE FROM order_items WHERE order_id NOT IN (SELECT order_id FROM orders)"),
     {"action_type 归类": 1, "方案能修根因": 2, "risk_level 判断": 3}),

    # 4. 空值 → 正确 fix_sql 回填 + 正确标 medium
    (Anomaly(type="null_rate", table="orders", column="order_delivered_customer_date"),
     Remediation(action_type="fix_sql", risk_level="medium",
                 sql_or_suggestion="UPDATE orders SET order_delivered_customer_date = order_estimated_delivery_date WHERE order_status='delivered' AND order_delivered_customer_date IS NULL"),
     {"action_type 归类": 5, "方案能修根因": 4, "risk_level 判断": 5}),

    # 5. 重复 → 错误 action_type（明明能 SQL 去重却开 ticket）
    (Anomaly(type="duplicate", table="orders", column="order_id"),
     Remediation(action_type="ticket", risk_level="low",
                 sql_or_suggestion="请人工排查重复订单"),
     {"action_type 归类": 1, "方案能修根因": 2, "risk_level 判断": 3}),

    # 6. 负价格 → fix_sql 但 WHERE 缺失（危险：会改全表）且没标 high
    (Anomaly(type="value_range", table="order_items", column="price"),
     Remediation(action_type="fix_sql", risk_level="low",
                 sql_or_suggestion="UPDATE order_items SET price = 0"),
     {"action_type 归类": 4, "方案能修根因": 1, "risk_level 判断": 1}),
]


def main() -> None:
    load_env(".env")
    model = LLMAdapter(DeepSeekClient())
    scores = [judge(model, a, r, RUBRIC).scores for a, r, _ in SAMPLES]
    labels = [label for _, _, label in SAMPLES]
    agree = judge_agreement(scores, labels)

    print(f"样本数 = {len(SAMPLES)}")
    print(f"judge_agreement（逐维度一致率）= {agree:.2%}")
    for i, (s, l) in enumerate(zip(scores, labels), 1):
        print(f"  #{i} judge={s} 人工={l}")


if __name__ == "__main__":
    main()
