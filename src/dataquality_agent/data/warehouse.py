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
        # Olist 采集端塌陷死区：2018-08-24 起日单量跌破 100、08-29 后 gmv=0，是采集截断不是真实波动。
        # orders 按 order_purchase_timestamp 截尾；order_items/payments/reviews 跟着甩掉尾部
        # （否则它们的 order_id 悬空，会被 check_orphan 误判成孤儿）。见设计文档 4.5。
        ORDERS_CUTOFF = "2018-08-24"
        for table, filename in ODS_FILES.items():
            path = data_dir / filename
            if path.exists():
                where = (f" WHERE order_purchase_timestamp < '{ORDERS_CUTOFF}'"
                         if table == "orders" else "")
                conn.execute(
                    f"CREATE OR REPLACE TABLE {table} AS "
                    f"SELECT * FROM read_csv('{path}', header=true, auto_detect=true){where}"
                )
                built.add(table)
        if "orders" in built:
            for child in ("order_items", "payments", "reviews"):
                if child in built:
                    conn.execute(
                        f"DELETE FROM {child} WHERE order_id NOT IN (SELECT order_id FROM orders)"
                    )

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

        # 2.6) DIM 日期维度：从下单日期拆出唯一日期轴（年/季/月/周/星期），供 ADS 宽表/趋势分析做维度。
        if "orders" in built:
            conn.execute("""
                CREATE OR REPLACE TABLE dim_date AS
                SELECT
                    date_key,
                    CAST(EXTRACT(YEAR FROM date_key) AS INTEGER) AS year,          -- 年
                    CAST(EXTRACT(QUARTER FROM date_key) AS INTEGER) AS quarter,    -- 季
                    CAST(EXTRACT(MONTH FROM date_key) AS INTEGER) AS month,        -- 月
                    CAST(EXTRACT(WEEK FROM date_key) AS INTEGER) AS week,          -- 周（ISO 周）
                    CAST(EXTRACT(ISODOW FROM date_key) AS INTEGER) AS day_of_week -- 星期（1=周一）
                FROM (
                    SELECT DISTINCT CAST(order_purchase_timestamp AS DATE) AS date_key
                    FROM dwd_orders
                )
                ORDER BY date_key
            """)

        # 3) DWS：聚合指标表（L1 volume/distribution 的多基线：daily_metrics 供 volume，dwd_orders/dwd_reviews 供 distribution）
        if {"orders", "order_items"} <= built:
            conn.execute("""
                CREATE OR REPLACE TABLE daily_metrics AS
                SELECT
                    CAST(o.order_purchase_timestamp AS TIMESTAMP)::DATE AS order_date,  -- 下单日期
                    COUNT(DISTINCT o.order_id) AS orders,                                -- 单量
                    COALESCE(SUM(i.price), 0.0) AS gmv,                                  -- GMV（成交额）
                    COALESCE(SUM(i.price), 0.0) / NULLIF(COUNT(DISTINCT o.order_id), 0) AS avg_order_value  -- 客单价
                FROM orders o
                LEFT JOIN order_items i ON o.order_id = i.order_id
                GROUP BY 1
                ORDER BY 1
            """) # GROUP BY 1和ORDER BY 1是位置引用，指SELECT列表的第1的表达式，即order_date，也就是按order_date分组和排序

        # DWS 补聚合（§14 #3）：seller/category/payment 三个横截面聚合表，补上 DWS 的「多基线」。
        # 读取口径沿用「需要 TRY_CAST 的列才走 DWD」：评分/金额/分期是 TRY_CAST 列 → 读 DWD；
        # price、product_category_name 在 ODS 已是干净 DOUBLE/字符串 → 读 ODS。
        if {"order_items", "reviews"} <= built:
            conn.execute("""
                CREATE OR REPLACE TABLE seller_metrics AS
                SELECT
                    i.seller_id,
                    COUNT(DISTINCT i.order_id) AS orders,   -- 单量（去重订单）
                    SUM(i.price) AS gmv,                    -- GMV（成交额）
                    AVG(r.review_score) AS avg_score        -- 平均评分（关联订单评价；一单多 seller 时评分重复计，检测导向可接受）
                FROM order_items i
                LEFT JOIN dwd_reviews r ON i.order_id = r.order_id
                GROUP BY i.seller_id
            """)
        if {"order_items", "products"} <= built:
            conn.execute("""
                CREATE OR REPLACE TABLE category_metrics AS
                SELECT
                    p.product_category_name,                 -- 品类名
                    COUNT(DISTINCT i.order_id) AS orders,    -- 单量（去重订单）
                    SUM(i.price) AS gmv,                     -- GMV（成交额）
                    COUNT(DISTINCT i.product_id) AS distinct_products  -- 品类下商品数
                FROM order_items i
                JOIN products p ON i.product_id = p.product_id
                GROUP BY p.product_category_name
            """)
        if "payments" in built:
            conn.execute("""
                CREATE OR REPLACE TABLE payment_summary AS
                SELECT
                    payment_type,                            -- 支付方式
                    COUNT(*) AS payments,                    -- 支付笔数
                    SUM(payment_value) AS total_value,       -- 支付总额
                    AVG(payment_installments) AS avg_installments  -- 平均分期期数
                FROM dwd_payments
                GROUP BY payment_type
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
