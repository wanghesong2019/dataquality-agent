"""跑一次案例检索的效果评测：Recall@K / MRR（证明检索链路，不只是"感觉能找到"）。

用法：cd 项目根 && python3 scripts/run_retrieval_eval.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dataquality_agent.eval.retrieval import evaluate_retrieval
from dataquality_agent.rag.cases import QUERIES, build_retriever


def main() -> None:
    retriever = build_retriever()
    report = evaluate_retrieval(retriever, QUERIES, k=3)
    print(f"案例库规模：{len(retriever.docs)} 条")
    print(f"Recall@3：{report['recall_at_k']:.3f}")
    print(f"MRR：{report['mrr']:.3f}")
    print("逐条（query -> 检索到的 top3 -> 期望）：")
    for q in QUERIES:
        ids = [r["id"] for r in retriever.search(q["query"], k=3)]
        hit = "OK " if q["relevant"] in ids else "MISS"
        print(f"  [{hit}] {q['query']!r} -> {ids}  (期望 {q['relevant']})")


if __name__ == "__main__":
    main()
