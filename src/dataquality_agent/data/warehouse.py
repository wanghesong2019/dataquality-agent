"""DuckDB 数仓构建：ODS → DWD → DWS。"""
from pathlib import Path

import duckdb

from dataquality_agent.config import Settings

# 文件名 → ODS 表名
ODS_FILES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "product_category_translation": "product_category_name_translation.csv",
}


class Warehouse:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._conn = None

    def connect(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(self.settings.db_path)
        return self._conn

    def build(self) -> None:
        conn = self.connect()
        data_dir = Path(self.settings.data_dir)
        built: set[str] = set()

        # 1) ODS：原始 CSV 落库（只读 data_dir 里实际存在的文件）
        for table, filename in ODS_FILES.items():
            path = data_dir / filename
            if path.exists():
                conn.execute(
                    f"CREATE OR REPLACE TABLE {table} AS "
                    f"SELECT * FROM read_csv('{path}', header=true, auto_detect=true)"
                )
                built.add(table)

        # 2) DWD：事实表类型转换（时间戳 → TIMESTAMP，金额 → DOUBLE）
        if "orders" in built:
            conn.execute("""
                CREATE OR REPLACE TABLE dwd_orders AS
                SELECT
                    order_id, customer_id, order_status,
                    CAST(order_purchase_timestamp AS TIMESTAMP) AS order_purchase_timestamp,
                    CAST(order_approved_at AS TIMESTAMP) AS order_approved_at,
                    CAST(order_delivered_carrier_date AS TIMESTAMP) AS order_delivered_carrier_date,
                    CAST(order_delivered_customer_date AS TIMESTAMP) AS order_delivered_customer_date,
                    CAST(order_estimated_delivery_date AS TIMESTAMP) AS order_estimated_delivery_date
                FROM orders
            """)
        if "order_items" in built:
            conn.execute("""
                CREATE OR REPLACE TABLE dwd_order_items AS
                SELECT
                    order_id, order_item_id, product_id, seller_id,
                    CAST(shipping_limit_date AS TIMESTAMP) AS shipping_limit_date,
                    CAST(price AS DOUBLE) AS price,
                    CAST(freight_value AS DOUBLE) AS freight_value
                FROM order_items
            """)

        # 3) DWS：日粒度指标表（L1 统计检测对比基线的对象）
        if {"orders", "order_items"} <= built:
            conn.execute("""
                CREATE OR REPLACE TABLE daily_metrics AS
                SELECT
                    CAST(o.order_purchase_timestamp AS TIMESTAMP)::DATE AS order_date,
                    COUNT(DISTINCT o.order_id) AS orders,
                    COALESCE(SUM(i.price), 0.0) AS gmv,
                    COALESCE(SUM(i.price), 0.0) / NULLIF(COUNT(DISTINCT o.order_id), 0) AS avg_order_value
                FROM orders o
                LEFT JOIN order_items i ON o.order_id = i.order_id
                GROUP BY 1
                ORDER BY 1
            """)
