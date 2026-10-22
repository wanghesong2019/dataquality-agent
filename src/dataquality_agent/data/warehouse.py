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
                    CAST(order_purchase_timestamp AS TIMESTAMP) AS order_purchase_timestamp,  -- 下单时间
                    CAST(order_approved_at AS TIMESTAMP) AS order_approved_at,  -- 支付批准时间
                    CAST(order_delivered_carrier_date AS TIMESTAMP) AS order_delivered_carrier_date,  -- 交付承运商时间（交给物流）
                    CAST(order_delivered_customer_date AS TIMESTAMP) AS order_delivered_customer_date,  -- 送达客户时间
                    CAST(order_estimated_delivery_date AS TIMESTAMP) AS order_estimated_delivery_date  -- 预计送达日期
                FROM orders
            """)
        if "order_items" in built:
            conn.execute("""
                CREATE OR REPLACE TABLE dwd_order_items AS
                SELECT
                    order_id, order_item_id, product_id, seller_id,
                    CAST(shipping_limit_date AS TIMESTAMP) AS shipping_limit_date,  -- 卖家最晚发货期限
                    CAST(price AS DOUBLE) AS price,
                    CAST(freight_value AS DOUBLE) AS freight_value  -- 运费
                FROM order_items
            """)

        # 2.5) DWD 补全：payments/reviews 事实表 + products/sellers/customers/geolocation 维度表。
        # 类型规范化用 TRY_CAST：空串/脏值 → NULL（ODS 保留原始证据，检测层 value_range/null_rate 负责抓脏值
        # ——分层职责 = 加载层健壮、检测层严格）。金额/时间/经纬度/数量转数值；纯字符串维度表锁 schema。
        if "payments" in built:
            conn.execute("""
                CREATE OR REPLACE TABLE dwd_payments AS
                SELECT
                    order_id,
                    TRY_CAST(payment_sequential AS INTEGER) AS payment_sequential,  -- 支付序号（同订单第几笔支付）
                    payment_type,
                    TRY_CAST(payment_installments AS INTEGER) AS payment_installments,  -- 分期期数
                    TRY_CAST(payment_value AS DOUBLE) AS payment_value  -- 支付金额
                FROM payments
            """)
        if "reviews" in built:
            conn.execute("""
                CREATE OR REPLACE TABLE dwd_reviews AS
                SELECT
                    review_id, order_id,
                    TRY_CAST(review_score AS INTEGER) AS review_score,  -- 评分（1~5）
                    review_comment_title, review_comment_message,
                    TRY_CAST(review_creation_date AS TIMESTAMP) AS review_creation_date,  -- 评价创建时间
                    TRY_CAST(review_answer_timestamp AS TIMESTAMP) AS review_answer_timestamp  -- 商家回复时间
                FROM reviews
            """)
        if "products" in built:
            conn.execute("""
                CREATE OR REPLACE TABLE dwd_products AS
                SELECT
                    product_id, product_category_name,
                    TRY_CAST(product_name_lenght AS INTEGER) AS product_name_lenght,
                    TRY_CAST(product_description_lenght AS INTEGER) AS product_description_lenght,
                    TRY_CAST(product_photos_qty AS INTEGER) AS product_photos_qty,  -- 商品图片数量
                    TRY_CAST(product_weight_g AS DOUBLE) AS product_weight_g,
                    TRY_CAST(product_length_cm AS DOUBLE) AS product_length_cm,
                    TRY_CAST(product_height_cm AS DOUBLE) AS product_height_cm,
                    TRY_CAST(product_width_cm AS DOUBLE) AS product_width_cm
                FROM products
            """)
        if "sellers" in built:
            conn.execute("""
                CREATE OR REPLACE TABLE dwd_sellers AS
                SELECT
                    seller_id,
                    seller_zip_code_prefix,  -- 卖家邮编前缀
                    seller_city,
                    seller_state
                FROM sellers
            """)
        if "customers" in built:
            conn.execute("""
                CREATE OR REPLACE TABLE dwd_customers AS
                SELECT customer_id, customer_unique_id, customer_zip_code_prefix, customer_city, customer_state
                FROM customers
            """)
        if "geolocation" in built:
            conn.execute("""
                CREATE OR REPLACE TABLE dwd_geolocation AS
                SELECT
                    geolocation_zip_code_prefix,  -- 邮编前缀
                    TRY_CAST(geolocation_lat AS DOUBLE) AS geolocation_lat,
                    TRY_CAST(geolocation_lng AS DOUBLE) AS geolocation_lng,
                    geolocation_city, geolocation_state
                FROM geolocation
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


def clone_warehouse(src_path: str, dst_path: str) -> None:
    """把 src 数仓完整复制到 dst（eval 在副本上注入，不污染干净数仓）。

    用 DuckDB `EXPORT/IMPORT DATABASE`（走临时目录）。不用 ATTACH：ATTACH 的文件句柄在
    close 后仍残留，会导致后续 connect(dst) 报 "already attached" 冲突。
    """
    import shutil
    import tempfile

    Path(dst_path).unlink(missing_ok=True)
    tmp = tempfile.mkdtemp(prefix="dqa_clone_")
    try:
        src = duckdb.connect(src_path)
        try:
            src.execute(f"EXPORT DATABASE '{tmp}'")
        finally:
            src.close()
        dst = duckdb.connect(dst_path)
        try:
            dst.execute(f"IMPORT DATABASE '{tmp}'")
        finally:
            dst.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
