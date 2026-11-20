"""内置样本数据（迷你 Olist 8 表），供 dqagent init 生成、开箱即用。"""
import pandas as pd


def write_sample_data(data_dir) -> None:
    """把迷你 Olist 8 表写成 CSV（与 tests/conftest.py 的 mini_data 同源），供开箱即用。"""
    data_dir.mkdir(parents=True, exist_ok=True)
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

    orders.to_csv(data_dir / "olist_orders_dataset.csv", index=False)
    items.to_csv(data_dir / "olist_order_items_dataset.csv", index=False)
    payments.to_csv(data_dir / "olist_order_payments_dataset.csv", index=False)
    reviews.to_csv(data_dir / "olist_order_reviews_dataset.csv", index=False)
    products.to_csv(data_dir / "olist_products_dataset.csv", index=False)
    sellers.to_csv(data_dir / "olist_sellers_dataset.csv", index=False)
    customers.to_csv(data_dir / "olist_customers_dataset.csv", index=False)
    geolocation.to_csv(data_dir / "olist_geolocation_dataset.csv", index=False)
