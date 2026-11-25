"""demo 数据集策展逻辑的单元测试：用内存里的迷你 Olist 验证各纯函数，不依赖全量数据。"""
import pandas as pd
import pytest

from dataquality_agent.data import demo


def _mini_olist():
    """6 单迷你 Olist：o1~o4 干净、o5 金额对不上、o6 取消且有评价。"""
    ts = lambda d: f"2018-01-0{d} 10:00:00"
    orders = pd.DataFrame({
        "order_id": ["o1", "o2", "o3", "o4", "o5", "o6"],
        "customer_id": ["c1", "c2", "c3", "c4", "c5", "c6"],
        "order_status": ["delivered", "delivered", "delivered", "delivered", "delivered", "canceled"],
        "order_purchase_timestamp": [ts(d) for d in range(1, 7)],
        "order_approved_at": [ts(d) for d in range(1, 7)],
        "order_delivered_carrier_date": [ts(d) for d in range(1, 7)],
        "order_delivered_customer_date": [ts(d) for d in range(1, 6)] + [None],
        "order_estimated_delivery_date": [ts(d) for d in range(1, 7)],
    })
    # o1~o5 各一单明细，price+freight=50；o5 的支付总额=20（对不上）
    items = pd.DataFrame({
        "order_id": ["o1", "o2", "o3", "o4", "o5"],
        "order_item_id": [1] * 5,
        "product_id": ["p1", "p2", "p3", "p4", "p5"],
        "seller_id": ["s1", "s2", "s3", "s4", "s5"],
        "shipping_limit_date": [ts(d) for d in range(1, 6)],
        "price": ["40.0"] * 5,
        "freight_value": ["10.0"] * 5,
    })
    payments = pd.DataFrame({
        "order_id": ["o1", "o2", "o3", "o4", "o5"],
        "payment_sequential": [1] * 5,
        "payment_type": ["credit_card"] * 5,
        "payment_installments": [1] * 5,
        "payment_value": ["50.0", "50.0", "50.0", "50.0", "20.0"],
    })
    reviews = pd.DataFrame({
        "review_id": ["r1", "r6"],
        "order_id": ["o1", "o6"],
        "review_score": ["5", "1"],
        "review_comment_title": ["ok", "bad"],
        "review_comment_message": ["bom", "ruim"],
        "review_creation_date": [ts(1), ts(6)],
        "review_answer_timestamp": [ts(1), ts(6)],
    })
    products = pd.DataFrame({
        "product_id": ["p1", "p2", "p3", "p4", "p5"],
        "product_category_name": ["cat"] * 5,
        "product_name_lenght": ["10"] * 5,
        "product_description_lenght": ["100"] * 5,
        "product_photos_qty": ["2"] * 5,
        "product_weight_g": ["500.0"] * 5,
        "product_length_cm": ["20.0"] * 5,
        "product_height_cm": ["10.0"] * 5,
        "product_width_cm": ["15.0"] * 5,
    })
    sellers = pd.DataFrame({
        "seller_id": ["s1", "s2", "s3", "s4", "s5"],
        "seller_zip_code_prefix": ["01001", "02001", "03001", "04001", "05001"],
        "seller_city": ["sao paulo", "rio", "bh", "porto", "curitiba"],
        "seller_state": ["SP", "RJ", "MG", "RS", "PR"],
    })
    customers = pd.DataFrame({
        "customer_id": ["c1", "c2", "c3", "c4", "c5", "c6"],
        "customer_unique_id": ["cu1", "cu2", "cu3", "cu4", "cu5", "cu6"],
        "customer_zip_code_prefix": ["01001", "02001", "03001", "04001", "05001", "06001"],
        "customer_city": ["sao paulo", "rio", "bh", "porto", "curitiba", "floripa"],
        "customer_state": ["SP", "RJ", "MG", "RS", "PR", "SC"],
    })
    # 01001 邮编映射两个城市（zip_inconsistency）
    geolocation = pd.DataFrame({
        "geolocation_zip_code_prefix": ["01001", "01001", "02001", "03001", "04001", "05001", "06001"],
        "geolocation_lat": ["-23.5", "-23.5", "-22.9", "-19.9", "-30.0", "-25.4", "-27.6"],
        "geolocation_lng": ["-46.6", "-46.6", "-43.2", "-43.9", "-51.2", "-49.2", "-48.5"],
        "geolocation_city": ["sao paulo", "guarulhos", "rio", "bh", "porto", "curitiba", "floripa"],
        "geolocation_state": ["SP", "SP", "RJ", "MG", "RS", "PR", "SC"],
    })
    translation = pd.DataFrame({
        "product_category_name": ["cat"],
        "product_category_name_english": ["category"],
    })
    return {
        "orders": orders, "order_items": items, "payments": payments, "reviews": reviews,
        "products": products, "sellers": sellers, "customers": customers,
        "geolocation": geolocation, "product_category_translation": translation,
    }


def _assert_referential(tables):
    orders = tables["orders"]
    items = tables["order_items"]
    oids = set(orders["order_id"])
    assert set(items["order_id"]) <= oids
    assert set(tables["payments"]["order_id"]) <= oids
    assert set(tables["reviews"]["order_id"]) <= oids
    assert set(items["product_id"]) <= set(tables["products"]["product_id"])
    assert set(items["seller_id"]) <= set(tables["sellers"]["seller_id"])
    assert set(orders["customer_id"]) <= set(tables["customers"]["customer_id"])
    assert orders["order_id"].is_unique
    assert orders["customer_id"].notna().all()


def test_sample_subset_is_referentially_consistent():
    tables = demo.sample_subset(_mini_olist(), n=3, seed=0)
    _assert_referential(tables)
    assert len(tables["orders"]) == 3


def test_sample_subset_respects_retention_cutoff():
    mini = _mini_olist()
    mini["orders"].loc[0, "order_purchase_timestamp"] = "2018-08-30 10:00:00"  # >= cutoff
    tables = demo.sample_subset(mini, n=5, seed=0)
    assert "o1" not in set(tables["orders"]["order_id"])  # 被截尾排除


def test_dedupe_geolocation_unique_city_per_zip():
    geo = demo.dedupe_geolocation(_mini_olist()["geolocation"])
    city_counts = geo.groupby("geolocation_zip_code_prefix")["geolocation_city"].nunique()
    assert (city_counts == 1).all()
    # 每邮编收敛到一行
    assert geo["geolocation_zip_code_prefix"].is_unique
    assert "01001" in set(geo["geolocation_zip_code_prefix"])


def test_clean_baseline_drops_canceled_reviews_and_mismatch():
    tables = demo.clean_baseline(_mini_olist())
    # o6 取消单的评价被删
    assert "o6" not in set(tables["reviews"]["order_id"])
    # o5 金额对不上被删（连同其子表行）
    assert "o5" not in set(tables["orders"]["order_id"])
    assert "o5" not in set(tables["order_items"]["order_id"])
    assert "o5" not in set(tables["payments"]["order_id"])
    # 邮编多城市被收敛
    assert tables["geolocation"].groupby("geolocation_zip_code_prefix")["geolocation_city"].nunique().eq(1).all()


def test_clean_baseline_drops_one_cent_mismatch():
    """边界单：支付 50.01 vs 明细 50.00（diff=0.01），float64 求和会舍到 0.01 以下漏删。"""
    mini = _mini_olist()
    mini["payments"].loc[mini["payments"]["order_id"] == "o1", "payment_value"] = "50.01"
    tables = demo.clean_baseline(mini)
    assert "o1" not in set(tables["orders"]["order_id"])


def test_inject_duplicate_creates_duplicate_groups():
    orders = _mini_olist()["orders"]
    out = demo.inject_duplicate(orders, n=2)
    dup_groups = out.groupby("order_id").size()
    assert (dup_groups > 1).sum() == 2  # 前 2 行各复制一次 → 2 组重复


def test_inject_orphan_drops_products():
    products = _mini_olist()["products"]
    out = demo.inject_orphan(products, n=2)
    assert len(out) == len(products) - 2
    assert "p1" not in set(out["product_id"])


def test_inject_null_rate_exceeds_threshold():
    orders = _mini_olist()["orders"]
    out = demo.inject_null_rate(orders, frac=0.5, seed=0)
    delivered = out[out["order_status"] == "delivered"]
    null_rate = delivered["order_delivered_customer_date"].isna().mean()
    assert null_rate > 0.05


def test_inject_value_range_negative_weight():
    products = _mini_olist()["products"]
    out = demo.inject_value_range(products, n=2)
    assert (out["product_weight_g"].astype(float) < 0).sum() == 2


def test_inject_join_fanout_duplicates_sellers():
    sellers = _mini_olist()["sellers"]
    out = demo.inject_join_fanout(sellers, n=2)
    assert (out.groupby("seller_id").size() > 1).sum() == 2  # 前 2 个卖家各复制一次


def test_inject_faults_applies_all_five():
    tables = demo.inject_faults(_mini_olist(), seed=0)
    orders = tables["orders"]
    # duplicate 生效
    assert (orders.groupby("order_id").size() > 1).sum() == 3
    # null_rate 生效（delivered 送达日期有空）
    delivered = orders[orders["order_status"] == "delivered"]
    assert delivered["order_delivered_customer_date"].isna().any()
    # orphan 生效：mini fixture 只有 5 个 product，n=20 全删光 → 无剩余可改重量
    assert len(tables["products"]) == 0
    # join_fanout 生效：卖家主键重复（维度表重复 → JOIN 膨胀根因）
    assert (tables["sellers"].groupby("seller_id").size() > 1).sum() == 2
