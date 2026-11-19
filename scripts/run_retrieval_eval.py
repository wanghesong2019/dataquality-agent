"""跑一次案例检索的效果评测：Recall@K / MRR（证明检索链路，不只是"感觉能找到"）。

用法：cd 项目根 && python3 scripts/run_retrieval_eval.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dataquality_agent.eval.retrieval import evaluate_retrieval
from dataquality_agent.rag.cases import CASE_REMEDY, QUERIES, build_retriever, load_flywheel_cases


def _flywheel_queries() -> list[dict]:
    """对飞轮增量案例自动生成 query：table + column + 类型描述，relevant = 案例 id。"""
    queries = []
    for c in load_flywheel_cases():
        if "table" not in c:  # 旧格式案例（无 table/column），跳过（需先 regenerate）
            continue
        desc = CASE_REMEDY.get(c["type"], ("异常", ""))[0]
        query = f"{c['table']} {c.get('column') or ''} {desc}".strip()
        queries.append({"query": query, "relevant": c["id"]})
    return queries


def main() -> None:
    retriever = build_retriever()
    queries = list(QUERIES) + _flywheel_queries()
    report = evaluate_retrieval(retriever, queries, k=3)
    n_static, n_fly = len(QUERIES), len(queries) - len(QUERIES)
    print(f"案例库规模：{len(retriever.docs)} 条")
    print(f"评测 query 数：{len(queries)}（静态 {n_static} + 飞轮 {n_fly}）")
    print(f"Recall@3：{report['recall_at_k']:.3f}")
    print(f"MRR：{report['mrr']:.3f}")
    print("逐条（query -> 检索到的 top3 -> 期望）：")
    for q in queries:
        ids = [r["id"] for r in retriever.search(q["query"], k=3)]
        hit = "OK " if q["relevant"] in ids else "MISS"
        print(f"  [{hit}] {q['query']!r} -> {ids}  (期望 {q['relevant']})")


if __name__ == "__main__":
    main()
