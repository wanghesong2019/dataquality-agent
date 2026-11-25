import duckdb
from pathlib import Path

from dataquality_agent.config import Settings
from dataquality_agent.data.warehouse import Warehouse, clone_warehouse


def test_warehouse_build_and_dws(mini_data):
    s = Settings(data_dir=str(mini_data), db_path=str(mini_data / "test.duckdb"))
    w = Warehouse(s)
    w.build()
    conn = w.connect()
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 3
    row = conn.execute(
        "SELECT orders, gmv, avg_order_value FROM daily_metrics WHERE order_date = DATE '2018-01-01'"
    ).fetchone()
    assert row[0] == 2
    assert row[1] == 35.0
    assert row[2] == 17.5


def test_warehouse_build_all_dwd(mini_data):
    """§14 #2：6 张新增 DWD 表都建成，类型/行数正确（TRY_CAST 规范化）。"""
    s = Settings(data_dir=str(mini_data), db_path=str(mini_data / "test.duckdb"))
    w = Warehouse(s)
    w.build()
    conn = w.connect()
    # 事实表
    assert conn.execute("SELECT COUNT(*) FROM dwd_payments").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM dwd_reviews").fetchone()[0] == 2
    assert conn.execute("SELECT typeof(payment_value) FROM dwd_payments LIMIT 1").fetchone()[0] == "DOUBLE"
    assert conn.execute("SELECT typeof(review_score) FROM dwd_reviews LIMIT 1").fetchone()[0] == "INTEGER"
    # 维度表
    assert conn.execute("SELECT COUNT(*) FROM dwd_products").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM dwd_sellers").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM dwd_customers").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM dwd_geolocation").fetchone()[0] == 2
    assert conn.execute("SELECT typeof(product_weight_g) FROM dwd_products LIMIT 1").fetchone()[0] == "DOUBLE"
    assert conn.execute("SELECT typeof(geolocation_lat) FROM dwd_geolocation LIMIT 1").fetchone()[0] == "DOUBLE"


def test_warehouse_build_dws_aggregates(mini_data):
    """§14 #3：seller/category/payment 三张 DWS 聚合表建好，口径正确（多基线）。"""
    s = Settings(data_dir=str(mini_data), db_path=str(mini_data / "test.duckdb"))
    w = Warehouse(s)
    w.build()
    conn = w.connect()

    # seller_metrics：GMV/单量/评分（s1 两单均价 4.5，s2 一单 5.0）
    sm = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        "SELECT seller_id, orders, gmv, avg_score FROM seller_metrics").fetchall()}
    assert sm["s1"] == (2, 15.0, 4.5)
    assert sm["s2"] == (1, 20.0, 5.0)

    # category_metrics：品类 GMV/单量
    cm = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT product_category_name, orders, gmv FROM category_metrics").fetchall()}
    assert cm["moveis_decoracao"] == (2, 15.0)
    assert cm["utilidades_domesticas"] == (1, 20.0)

    # payment_summary：分期/支付方式（boleto 3 期，其余 1 期）
    ps = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        "SELECT payment_type, payments, total_value, avg_installments FROM payment_summary").fetchall()}
    assert ps["credit_card"] == (1, 15.0, 1.0)
    assert ps["voucher"] == (1, 20.0, 1.0)
    assert ps["boleto"] == (1, 6.0, 3.0)


def test_clone_warehouse(mini_warehouse):
    dst = str(Path(mini_warehouse.db_path).with_name("clone.duckdb"))
    clone_warehouse(mini_warehouse.db_path, dst)

    src = duckdb.connect(mini_warehouse.db_path)
    clone = duckdb.connect(dst)
    src_tables = sorted(t[0] for t in src.execute("SHOW TABLES").fetchall())
    clone_tables = sorted(t[0] for t in clone.execute("SHOW TABLES").fetchall())
    assert src_tables == clone_tables
    for t in src_tables:
        assert clone.execute(f"SELECT COUNT(*) FROM {t}").fetchone() == src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()

    # 改 clone 不影响原库：eval 在副本上注入，不污染干净数仓
    before = src.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    clone.execute("INSERT INTO orders SELECT * FROM orders LIMIT 1")
    assert src.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == before
    assert clone.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == before + 1


def test_dim_date_covers_all_order_dates(mini_data):
    """dim_date 一行一个 distinct 下单日期；year/quarter/month 与 date_key 一致。"""
    s = Settings(data_dir=str(mini_data), db_path=str(mini_data / "test.duckdb"))
    w = Warehouse(s)
    w.build()
    conn = w.connect()
    distinct_dates = conn.execute(
        "SELECT COUNT(DISTINCT CAST(order_purchase_timestamp AS DATE)) FROM dwd_orders"
    ).fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM dim_date").fetchone()[0] == distinct_dates
    row = conn.execute(
        "SELECT year, quarter, month FROM dim_date WHERE date_key = DATE '2018-01-01'"
    ).fetchone()
    assert row == (2018, 1, 1)


def test_dim_date_columns_typed(mini_data):
    """dim_date 的 date_key 是 DATE、year/month 是 INTEGER（EXTRACT 规范化）。"""
    s = Settings(data_dir=str(mini_data), db_path=str(mini_data / "test.duckdb"))
    w = Warehouse(s)
    w.build()
    conn = w.connect()
    assert conn.execute("SELECT typeof(date_key) FROM dim_date LIMIT 1").fetchone()[0] == "DATE"
    assert conn.execute("SELECT typeof(year) FROM dim_date LIMIT 1").fetchone()[0] == "INTEGER"
    assert conn.execute("SELECT typeof(month) FROM dim_date LIMIT 1").fetchone()[0] == "INTEGER"


def test_dim_tables_unique_pk(mini_data):
    """五张维度表各自主键唯一（customer/seller/product/geolocation/category）。"""
    s = Settings(data_dir=str(mini_data), db_path=str(mini_data / "test.duckdb"))
    w = Warehouse(s)
    w.build()
    conn = w.connect()
    for table, pk in [
        ("dim_customer", "customer_id"),
        ("dim_seller", "seller_id"),
        ("dim_product", "product_id"),
        ("dim_geolocation", "zip_prefix"),
        ("dim_category", "product_category_name"),
    ]:
        total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        distinct = conn.execute(f"SELECT COUNT(DISTINCT {pk}) FROM {table}").fetchone()[0]
        assert total > 0, f"{table} is empty"
        assert total == distinct, f"{table} has duplicate {pk}"


def test_dim_geolocation_dedupes_to_one_row_per_zip(mini_data):
    """dim_geolocation 一邮编一行，且取众数城市（同邮编多城市时按出现次数取最多的）。"""
    import pandas as pd

    geo_path = mini_data / "olist_geolocation_dataset.csv"
    geo = pd.read_csv(geo_path)
    # 给 01001 再补两行：sao paulo（第二行）+ campinas → 01001 共 sao paulo×2 / campinas×1，众数 = sao paulo
    extra = pd.DataFrame({
        "geolocation_zip_code_prefix": ["01001", "01001"],
        "geolocation_lat": [-23.5, -22.9],
        "geolocation_lng": [-46.6, -47.0],
        "geolocation_city": ["sao paulo", "campinas"],
        "geolocation_state": ["SP", "SP"],
    })
    pd.concat([geo, extra], ignore_index=True).to_csv(geo_path, index=False)

    s = Settings(data_dir=str(mini_data), db_path=str(mini_data / "test.duckdb"))
    w = Warehouse(s)
    w.build()
    conn = w.connect()
    assert conn.execute("SELECT COUNT(*) FROM dim_geolocation").fetchone()[0] == \
           conn.execute("SELECT COUNT(DISTINCT zip_prefix) FROM dim_geolocation").fetchone()[0]
    city = conn.execute("SELECT geolocation_city FROM dim_geolocation WHERE zip_prefix = '01001'").fetchone()[0]
    assert city == "sao paulo"
