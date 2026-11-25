"""声明式 L0 断言目录：YAML 声明（表+列+条件+阈值）→ 编译成带证据的 Detector。

「一切皆断言」里 declaration 那一半的落地——用户不 fork 代码就能声明自己的断言。
五种类型映射到 rules.py 的 check_* 参考实现，异常仍带结构化 Evidence。
"""
from dataclasses import dataclass
from pathlib import Path

import yaml

from dataquality_agent.models import Anomaly


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

    def __post_init__(self):
        # referential 的 parent_column 缺省 = child_column（load_assertions 也补，这里兜住直接构造的路径）
        if self.type == "referential" and self.parent_column is None:
            self.parent_column = self.child_column

    def check(self, adapter) -> list[Anomaly]:
        """按 type 分发到 rules.py 的 check_* 参考实现，复用 sample_offending + Evidence；应用 severity。

        check_* 函数在方法内懒导入：rules.py 会反过来 import 本模块（default_assertions / run_catalog_checks），
        顶层互导会成环，运行时导入则无环。
        """
        from dataquality_agent.detection.rules import (
            check_duplicate, check_null_rate, check_orphan, check_value_range,
        )
        if self.type == "unique":
            result = check_duplicate(adapter, self.table, self.columns)
        elif self.type == "not_null":
            result = check_null_rate(adapter, self.table, self.column, threshold=0.0)
        elif self.type == "null_rate":
            result = check_null_rate(adapter, self.table, self.column, threshold=self.max_rate, where=self.where)
        elif self.type == "value_range":
            result = check_value_range(adapter, self.table, self.column, self.min, self.max)
        elif self.type == "referential":
            result = check_orphan(adapter, self.child_table, self.parent_table, self.child_column, self.parent_column)
        else:
            result = []
        for a in result:
            a.severity = self.severity
        return result


def _require(item: dict, key: str, name: str) -> str:
    v = item.get(key)
    if not v:
        raise ValueError(f"assertion {name} missing {key}")
    return v


def load_assertions(path) -> list[Assertion]:
    """读 YAML、校验 schema（未知 type / 缺字段 / 值域非法 → fail-fast），返回断言列表。

    目录是用户自配的受信配置；`where` 是原始 SQL 片段（dbt 风格），不做 SQL 解析。
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "assertions" not in data:
        raise ValueError("assertions.yaml needs a top-level 'assertions' list")
    raw = data["assertions"]
    if not isinstance(raw, list):
        raise ValueError("'assertions' must be a list")

    assertions: list[Assertion] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"each assertion must be a mapping, got {item!r}")
        name = item.get("name")
        if not name:
            raise ValueError("assertion missing name")
        if name in seen:
            raise ValueError(f"duplicate assertion name: {name}")
        seen.add(name)

        typ = item.get("type")
        if typ not in ASSERTION_TYPES:
            raise ValueError(f"unknown assertion type: {typ} (allowed: {sorted(ASSERTION_TYPES)})")
        severity = item.get("severity", "medium")

        if typ == "unique":
            cols = item.get("columns")
            if not cols or not isinstance(cols, list):
                raise ValueError(f"unique assertion {name} needs a non-empty columns list")
            assertions.append(Assertion(name=name, type=typ, table=_require(item, "table", name),
                                        columns=cols, severity=severity))
        elif typ in ("not_null", "null_rate"):
            max_rate = item.get("max_rate")
            if typ == "null_rate" and max_rate is None:
                raise ValueError(f"null_rate assertion {name} needs max_rate")
            assertions.append(Assertion(name=name, type=typ, table=_require(item, "table", name),
                                        column=_require(item, "column", name), max_rate=max_rate,
                                        where=item.get("where"), severity=severity))
        elif typ == "value_range":
            min_v, max_v = item.get("min"), item.get("max")
            if min_v is None and max_v is None:
                raise ValueError(f"value_range assertion {name} needs min or max (at least one)")
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


def run_catalog_checks(adapter, assertions: list[Assertion]) -> list[Anomaly]:
    """逐个跑断言，单条失败隔离（不拖垮整次巡检），合并异常。"""
    anomalies: list[Anomaly] = []
    for assertion in assertions:
        try:
            anomalies += assertion.check(adapter)
        except Exception:
            pass  # 隔离：一条坏断言（坏 where / 坏列）不拖垮整次巡检
    return anomalies


def default_assertions(null_rate_threshold: float = 0.05) -> list[Assertion]:
    """内置 Olist 默认断言目录（= 现状 run_rule_checks 的通用 L0 规则，17 条）。

    delivered 日期空值检查的阈值从参数注入，让 Settings.null_rate_threshold 继续控制它。
    """
    return [
        # unique
        Assertion(name="orders_unique_order_id", type="unique", table="orders", columns=["order_id"]),
        Assertion(name="order_items_unique_id", type="unique", table="order_items", columns=["order_id", "order_item_id"]),
        Assertion(name="payments_unique_id", type="unique", table="payments", columns=["order_id", "payment_sequential"]),
        Assertion(name="reviews_unique_id", type="unique", table="reviews", columns=["review_id"]),
        # referential（星型模型 FK 网）
        Assertion(name="order_items_ref_orders", type="referential", child_table="order_items", child_column="order_id", parent_table="orders"),
        Assertion(name="order_items_ref_products", type="referential", child_table="order_items", child_column="product_id", parent_table="products"),
        Assertion(name="order_items_ref_sellers", type="referential", child_table="order_items", child_column="seller_id", parent_table="sellers"),
        Assertion(name="payments_ref_orders", type="referential", child_table="payments", child_column="order_id", parent_table="orders"),
        Assertion(name="reviews_ref_orders", type="referential", child_table="reviews", child_column="order_id", parent_table="orders"),
        Assertion(name="orders_ref_customers", type="referential", child_table="orders", child_column="customer_id", parent_table="customers"),
        # value_range
        Assertion(name="order_items_price_non_negative", type="value_range", table="order_items", column="price", min=0),
        Assertion(name="order_items_freight_non_negative", type="value_range", table="order_items", column="freight_value", min=0),
        Assertion(name="products_weight_non_negative", type="value_range", table="products", column="product_weight_g", min=0),
        Assertion(name="reviews_score_in_range", type="value_range", table="reviews", column="review_score", min=1, max=5),
        Assertion(name="payments_installments_in_range", type="value_range", table="payments", column="payment_installments", min=1, max=24),
        # null_rate / not_null
        Assertion(name="orders_delivered_date_null_rate", type="null_rate", table="orders", column="order_delivered_customer_date",
                  max_rate=null_rate_threshold, where="order_status = 'delivered'"),
        Assertion(name="orders_customer_not_null", type="not_null", table="orders", column="customer_id"),
        # dim 维度表主键唯一（维度建模不变式：规范维度表 PK 唯一，重复即建模/加载故障）
        Assertion(name="dim_customer_unique_id", type="unique", table="dim_customer", columns=["customer_id"]),
        Assertion(name="dim_seller_unique_id", type="unique", table="dim_seller", columns=["seller_id"]),
        Assertion(name="dim_product_unique_id", type="unique", table="dim_product", columns=["product_id"]),
        Assertion(name="dim_geolocation_unique_zip", type="unique", table="dim_geolocation", columns=["zip_prefix"]),
        Assertion(name="dim_category_unique_name", type="unique", table="dim_category", columns=["product_category_name"]),
    ]


def build_assertion_detector(assertions: list[Assertion]):
    """把断言列表包成一个 Detector（满足 name + detect(adapter, ctx) 协议），供注册进 DETECTORS。"""
    class CatalogDetector:
        name = "assertion_catalog"

        def detect(self, adapter, ctx):
            return run_catalog_checks(adapter, assertions)

    return CatalogDetector()
