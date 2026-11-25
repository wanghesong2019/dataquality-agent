"""共享 fixtures：迷你 Olist 数据 + 迷你数仓（多个测试文件复用）。"""
import pandas as pd
import pytest

from dataquality_agent.config import Settings
from dataquality_agent.data.warehouse import Warehouse


@pytest.fixture
def mini_data(tmp_path):
    """3 单的迷你 Olist 数据，让单元测试快且不依赖 100MB 真实数据。"""
    orders = pd.DataFrame({
        "order_id": ["o1", "o2", "o3"],
        "customer_id": ["c1", "c2", "c3"],
        "order_status": ["delivered", "delivered", "canceled"],
        "order_purchase_timestamp": ["2018-01-01 10:00:00", "2018-01-01 11:00:00", "2018-01-02 09:00:00"],
        "order_approved_at": ["2018-01-01 10:30:00", "2018-01-01 11:30:00", None],
        "order_delivered_carrier_date": ["2018-01-03 00:00:00", "2018-01-04 00:00:00", None],
        "order_delivered_customer_date": ["2018-01-05 00:00:00", "2018-01-06 00:00:00", None],
        "order_estimated_delivery_date": ["2018-01-08 00:00:00", "2018-01-09 00:00:00", "2018-01-10 00:00:00"],
    })
    items = pd.DataFrame({
        "order_id": ["o1", "o1", "o2"],
        "order_item_id": [1, 2, 1],
        "product_id": ["p1", "p2", "p1"],
        "seller_id": ["s1", "s2", "s1"],
        "shipping_limit_date": ["2018-01-02 00:00:00"] * 3,
        "price": [10.0, 20.0, 5.0],
        "freight_value": [2.0, 3.0, 1.0],
    })
    orders.to_csv(tmp_path / "olist_orders_dataset.csv", index=False)
    items.to_csv(tmp_path / "olist_order_items_dataset.csv", index=False)

    # §14 数据基座升级：补 6 张表的迷你数据（FK 与 orders/items 对齐），供 DWD 补全测试复用
    payments = pd.DataFrame({
        "order_id": ["o1", "o1", "o2"],
        "payment_sequential": [1, 2, 1],
        "payment_type": ["credit_card", "voucher", "boleto"],
        "payment_installments": [1, 1, 3],
        "payment_value": [15.0, 20.0, 6.0],
    })
    reviews = pd.DataFrame({
        "review_id": ["r1", "r2"],
        "order_id": ["o1", "o2"],
        "review_score": [5, 4],
        "review_comment_title": ["bom", "ok"],
        "review_comment_message": ["otimo", "razoavel"],
        "review_creation_date": ["2018-01-05 00:00:00", "2018-01-06 00:00:00"],
        "review_answer_timestamp": ["2018-01-06 00:00:00", "2018-01-07 00:00:00"],
    })
    products = pd.DataFrame({
        "product_id": ["p1", "p2"],
        "product_category_name": ["moveis_decoracao", "utilidades_domesticas"],
        "product_name_lenght": [50, 40],
        "product_description_lenght": [200, 150],
        "product_photos_qty": [3, 2],
        "product_weight_g": [1200.0, 800.0],
        "product_length_cm": [30.0, 20.0],
        "product_height_cm": [10.0, 8.0],
        "product_width_cm": [20.0, 15.0],
    })
    sellers = pd.DataFrame({
        "seller_id": ["s1", "s2"],
        "seller_zip_code_prefix": ["01001", "02001"],
        "seller_city": ["sao paulo", "rio de janeiro"],
        "seller_state": ["SP", "RJ"],
    })
    customers = pd.DataFrame({
        "customer_id": ["c1", "c2", "c3"],
        "customer_unique_id": ["cu1", "cu2", "cu3"],
        "customer_zip_code_prefix": ["01001", "02001", "03001"],
        "customer_city": ["sao paulo", "rio de janeiro", "belo horizonte"],
        "customer_state": ["SP", "RJ", "MG"],
    })
    geolocation = pd.DataFrame({
        "geolocation_zip_code_prefix": ["01001", "02001"],
        "geolocation_lat": [-23.5, -22.9],
        "geolocation_lng": [-46.6, -43.2],
        "geolocation_city": ["sao paulo", "rio de janeiro"],
        "geolocation_state": ["SP", "RJ"],
    })
    for name, df in [
        ("olist_order_payments_dataset", payments),
        ("olist_order_reviews_dataset", reviews),
        ("olist_products_dataset", products),
        ("olist_sellers_dataset", sellers),
        ("olist_customers_dataset", customers),
        ("olist_geolocation_dataset", geolocation),
    ]:
        df.to_csv(tmp_path / f"{name}.csv", index=False)

    # 品类名英译表（dim_category 的原料，mini 样例补上以覆盖维度层）
    translation = pd.DataFrame({
        "product_category_name": ["moveis_decoracao", "utilidades_domesticas"],
        "product_category_name_english": ["furniture_decor", "housewares"],
    })
    translation.to_csv(tmp_path / "product_category_name_translation.csv", index=False)
    return tmp_path


@pytest.fixture
def mini_warehouse(mini_data):
    """在迷你数据上构建数仓，返回 Settings。"""
    settings = Settings(data_dir=str(mini_data), db_path=str(mini_data / "test.duckdb"))
    Warehouse(settings).build()
    return settings


@pytest.fixture
def postgres_warehouse(mini_data):
    """把 mini Olist ODS 数据载入真实 Postgres，返回 psycopg 连接（无 POSTGRES_DSN 时跳过）。"""
    import os

    import psycopg

    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        pytest.skip("POSTGRES_DSN not set")

    # 类型规则：时间戳列 → TIMESTAMP（check_future_date/check_time_inversion 依赖），数值 → DOUBLE/INTEGER，其余 TEXT
    tables = {
        "orders": ("order_id TEXT, customer_id TEXT, order_status TEXT, "
                   "order_purchase_timestamp TIMESTAMP, order_approved_at TIMESTAMP, "
                   "order_delivered_carrier_date TIMESTAMP, order_delivered_customer_date TIMESTAMP, "
                   "order_estimated_delivery_date TIMESTAMP"),
        "order_items": ("order_id TEXT, order_item_id INTEGER, product_id TEXT, seller_id TEXT, "
                        "shipping_limit_date TIMESTAMP, price DOUBLE PRECISION, freight_value DOUBLE PRECISION"),
        "payments": ("order_id TEXT, payment_sequential INTEGER, payment_type TEXT, "
                     "payment_installments INTEGER, payment_value DOUBLE PRECISION"),
        "reviews": ("review_id TEXT, order_id TEXT, review_score INTEGER, review_comment_title TEXT, "
                    "review_comment_message TEXT, review_creation_date TIMESTAMP, review_answer_timestamp TIMESTAMP"),
        "products": ("product_id TEXT, product_category_name TEXT, product_name_lenght INTEGER, "
                     "product_description_lenght INTEGER, product_photos_qty INTEGER, "
                     "product_weight_g DOUBLE PRECISION, product_length_cm DOUBLE PRECISION, "
                     "product_height_cm DOUBLE PRECISION, product_width_cm DOUBLE PRECISION"),
        "sellers": "seller_id TEXT, seller_zip_code_prefix TEXT, seller_city TEXT, seller_state TEXT",
        "customers": "customer_id TEXT, customer_unique_id TEXT, customer_zip_code_prefix TEXT, customer_city TEXT, customer_state TEXT",
        "geolocation": "geolocation_zip_code_prefix TEXT, geolocation_lat DOUBLE PRECISION, geolocation_lng DOUBLE PRECISION, geolocation_city TEXT, geolocation_state TEXT",
    }
    csv_files = {
        "orders": "olist_orders_dataset.csv",
        "order_items": "olist_order_items_dataset.csv",
        "payments": "olist_order_payments_dataset.csv",
        "reviews": "olist_order_reviews_dataset.csv",
        "products": "olist_products_dataset.csv",
        "sellers": "olist_sellers_dataset.csv",
        "customers": "olist_customers_dataset.csv",
        "geolocation": "olist_geolocation_dataset.csv",
    }

    conn = psycopg.connect(dsn)
    conn.autocommit = True  # DDL/COPY 即时生效，免 commit 样板
    try:
        for table, ddl in tables.items():
            conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            conn.execute(f"CREATE TABLE {table} ({ddl})")
            with (mini_data / csv_files[table]).open("rb") as f, conn.cursor() as cur:
                with cur.copy(f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')") as copy:
                    copy.write(f.read())
        yield conn
    finally:
        for table in tables:
            conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        conn.close()
