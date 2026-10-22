"""中文分词：英文/数字按空白切、中文切成字符 bigram（无外部依赖，替代 text.split()）。

为什么需要它：text.split() 只按空白切，中文词之间没有空白，会把「主键重复，上游」当成一个
token，BM25/词袋都吃不到「主键」「重复」这些词项，检索对中文几乎失效（Recall@3 实测 0.3）。

方案：字符 bigram（中文信息检索的经典无词典分词）——"主键重复" → ["主键","键重","重复"]，
能捕获词边界；英文/数字/下划线整段保留。生产可换 jieba 词典分词或 BGE-M3 subword，接口不变。
"""
import re

_TOKEN_RE = re.compile(r"[一-鿿]+|[A-Za-z0-9_]+")


def tokenize(text: str) -> list[str]:
    """把文本切成词项：中文段切成字符 bigram，英文/数字/下划线整段保留。"""
    tokens: list[str] = []
    for part in _TOKEN_RE.findall(text):
        if "一" <= part[0] <= "鿿":  # 中文段
            tokens += [part[i:i + 2] for i in range(len(part) - 1)] if len(part) > 1 else [part]
        else:
            tokens.append(part)
    return tokens
