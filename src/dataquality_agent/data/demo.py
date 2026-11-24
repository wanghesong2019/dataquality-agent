"""策展 demo 数据集：全量 Olist → 真实子集 + 注入故障（供录屏 / 本地演示）。

从全量 Olist 采一个真实、referential 一致的子集，清掉全量数据自带的 always-on
脏数据（金额对不上 / 取消单有评价 / 邮编多城市），再注入 4 类真实故障模式：

  - JOIN 膨胀 → 主键重复（duplicate）
  - 上游断更 → 孤儿（orphan）
  - 脏值 → 关键列置空（null_rate）
  - 脏值 → 负重量（value_range）

产出目录结构与 data.sample.write_sample_data 一致（8 表 + translation CSV），
可直接 `dqagent detect --dir <out>` / `dqagent run --dir <out>`。

注意：本模块只做「数据策展」，不落 DuckDB；CSV 层的注入与 injector.Injector 的
DuckDB 层注入语义对齐（duplicate 复制前 n 行、orphan 删前 n 个父表行等），保证
检出结果与 eval 口径一致。
"""
from pathlib import Path

import pandas as pd

from dataquality_agent.data.warehouse import ODS_FILES

# warehouse.build 对 orders 的 retention-window 截尾：>= 该日期的订单会在建仓时被丢弃。
# 采样时同步截尾，避免「采样后又截尾」导致子表悬空 / 单量对不上。
ORDERS_CUTOFF = "2018-08-24"


def read_olist(src_dir) -> dict[str, pd.DataFrame]:
    """读全量 Olist 9 表。全部按 str 读入：保留前导零（邮编）、时间戳原样、null→NaN。"""
    tables: dict[str, pd.DataFrame] = {}
    for name, filename in ODS_FILES.items():
        path = Path(src_dir) / filename
        if path.exists():
            tables[name] = pd.read_csv(path, dtype=str)
    return tables


def sample_subset(tables: dict[str, pd.DataFrame], n: int, seed: int = 0) -> dict[str, pd.DataFrame]:
    """采 n 个订单，并按 FK 收敛子表 + 维度表，保证 referential 一致（无孤儿 / 无悬空）。"""
    orders = tables["orders"]
    orders = orders[orders["order_purchase_timestamp"] < ORDERS_CUTOFF]
    orders = orders.sample(n=min(n, len(orders)), random_state=seed)
    oids = set(orders["order_id"])

    items = tables["order_items"]
    items = items[items["order_id"].isin(oids)]
    payments = tables["payments"]
    payments = payments[payments["order_id"].isin(oids)]
    reviews = tables["reviews"]
    reviews = reviews[reviews["order_id"].isin(oids)]

    products = tables["products"]
    products = products[products["product_id"].isin(set(items["product_id"]))]
    sellers = tables["sellers"]
    sellers = sellers[sellers["seller_id"].isin(set(items["seller_id"]))]
    customers = tables["customers"]
    customers = customers[customers["customer_id"].isin(set(orders["customer_id"]))]

    zips = set(customers["customer_zip_code_prefix"]) | set(sellers["seller_zip_code_prefix"])
    geolocation = tables["geolocation"]
    geolocation = geolocation[geolocation["geolocation_zip_code_prefix"].isin(zips)]

    return {
        "orders": orders.reset_index(drop=True),
        "order_items": items.reset_index(drop=True),
        "payments": payments.reset_index(drop=True),
        "reviews": reviews.reset_index(drop=True),
        "products": products.reset_index(drop=True),
        "sellers": sellers.reset_index(drop=True),
        "customers": customers.reset_index(drop=True),
        "geolocation": geolocation.reset_index(drop=True),
        "product_category_translation": tables.get("product_category_translation"),
    }


def dedupe_geolocation(geolocation: pd.DataFrame) -> pd.DataFrame:
    """每个邮编只保留「最常见城市」的一行，消除 zip→多城市 矛盾（zip_inconsistency）。

    Olist 的 geolocation 是坐标表（同一邮编 ~53 个经纬点），demo 只当邮编→城市/州查找表用，
    收敛到每邮编一行，省去 44 万行无用的坐标点。
    """
    if geolocation.empty:
        return geolocation
    mode_city = geolocation.groupby("geolocation_zip_code_prefix")["geolocation_city"].agg(
        lambda s: s.mode().iloc[0]
    ).rename("_keep_city")
    merged = geolocation.merge(mode_city, left_on="geolocation_zip_code_prefix", right_index=True)
    return (merged[merged["geolocation_city"] == merged["_keep_city"]]
            .drop_duplicates("geolocation_zip_code_prefix")
            .drop(columns="_keep_city").reset_index(drop=True))


def clean_baseline(tables: dict[str, pd.DataFrame], tol: float = 0.005) -> dict[str, pd.DataFrame]:
    """清掉全量 Olist 自带的 always-on 脏数据，得到干净基线。

    - state_conflict：删掉取消单的评价。
    - amount_mismatch：删掉「支付总额 vs 明细总额」对不上的订单（连同其子表行）。
    - zip_inconsistency：邮编收敛到单一城市。

    tol 取 0.005（而非检测层的 0.01）：Olist 的真实金额对不上常是「差一分钱」（diff≈0.01），
    pandas float64 求和与 DuckDB 的 DECIMAL/DOUBLE 求和在 0.01 边界会往相反方向舍入，
    导致本该删的单漏删。0.005 留出安全边际，把这类边界单一律删掉（demo 只关心干净基线）。
    """
    orders = tables["orders"]
    items = tables["order_items"]
    payments = tables["payments"]
    reviews = tables["reviews"]

    canceled = set(orders.loc[orders["order_status"] == "canceled", "order_id"])
    if canceled:
        reviews = reviews[~reviews["order_id"].isin(canceled)]

    item_total = items.assign(_t=items["price"].astype(float) + items["freight_value"].astype(float)) \
        .groupby("order_id")["_t"].sum()
    pay_total = payments.groupby("order_id")["payment_value"].apply(lambda s: s.astype(float).sum())
    common = item_total.index.intersection(pay_total.index)
    bad = {oid for oid in common if abs(item_total[oid] - pay_total[oid]) > tol}
    if bad:
        orders = orders[~orders["order_id"].isin(bad)]
        items = items[~items["order_id"].isin(bad)]
        payments = payments[~payments["order_id"].isin(bad)]
        reviews = reviews[~reviews["order_id"].isin(bad)]

    return {
        **tables,
        "orders": orders.reset_index(drop=True),
        "order_items": items.reset_index(drop=True),
        "payments": payments.reset_index(drop=True),
        "reviews": reviews.reset_index(drop=True),
        "geolocation": dedupe_geolocation(tables["geolocation"]),
    }


def inject_duplicate(orders: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    """复制前 n 行 → n 组主键重复（对应 injector.inject_duplicate 的 `LIMIT n`）。"""
    return pd.concat([orders, orders.head(n)], ignore_index=True)


def inject_orphan(products: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """删前 n 个商品 → order_items 的 product_id 悬空（对应 injector.inject_orphan 删父表前 n 行）。"""
    return products.iloc[n:].reset_index(drop=True)


def inject_null_rate(orders: pd.DataFrame, frac: float = 0.10, seed: int = 0) -> pd.DataFrame:
    """把 frac 比例的 delivered 订单送达日期置空，拉高 null 率越过 5% 阈值。"""
    delivered_idx = orders[orders["order_status"] == "delivered"].sample(frac=frac, random_state=seed).index
    orders.loc[delivered_idx, "order_delivered_customer_date"] = None
    return orders


def inject_value_range(products: pd.DataFrame, n: int = 3, bad_value: float = -5.0) -> pd.DataFrame:
    """前 n 个商品重量改成负值，制造值域异常（product_weight_g < 0）。

    不碰 price/freight：改价格会让「支付总额 vs 明细总额」也跟着对不上，污染 amount_mismatch
    （它 SUM(price+freight)），把一条注入异变成两条。改重量（维度表属性）是隔离的。
    """
    idx = products.head(n).index
    products.loc[idx, "product_weight_g"] = str(bad_value)
    return products


def inject_faults(tables: dict[str, pd.DataFrame], seed: int = 0) -> dict[str, pd.DataFrame]:
    """注入 4 类真实故障模式，返回注入后的表。

    duplicate 与 null_rate 都作用在 orders，按顺序叠加（先复制、再置空），不能互相覆盖。
    orphan 与 value_range 都作用在 products，按顺序叠加（先删 20 个、再改剩余前 3 个重量），
    保证删的和改的不是同一批商品。
    """
    orders = inject_duplicate(tables["orders"], n=3)
    orders = inject_null_rate(orders, frac=0.10, seed=seed)
    products = inject_orphan(tables["products"], n=20)
    products = inject_value_range(products, n=3)
    return {
        **tables,
        "orders": orders,
        "products": products,
    }


def build_demo_dataset(src_dir, n: int = 5000, seed: int = 0) -> dict[str, pd.DataFrame]:
    """端到端策展：读全量 Olist → 采样 → 清基线 → 注入故障。"""
    tables = read_olist(src_dir)
    tables = sample_subset(tables, n, seed)
    tables = clean_baseline(tables)
    tables = inject_faults(tables, seed)
    return tables


def write_demo_data(tables: dict[str, pd.DataFrame], out_dir) -> None:
    """把 9 张表写成 CSV 到 out_dir/data/（与 CLI 的 `--dir`/data 布局一致）。"""
    data_dir = Path(out_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, filename in ODS_FILES.items():
        df = tables.get(name)
        if df is not None:
            df.to_csv(data_dir / filename, index=False)
