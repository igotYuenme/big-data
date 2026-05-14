"""
淘宝用户行为数据分析：从 Hive 拉取聚合结果，失败时回退 docs/data 下 CSV；
使用 Pyecharts 生成交互式图表配置（标题、坐标轴、数据标签）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from pyecharts import options as opts
from pyecharts.charts import Bar, Funnel, HeatMap, Line, Pie
from pyecharts.globals import ThemeType

from .hive_client import (
    configure_hive_session,
    force_local_mode,
    get_hive_connection,
    is_hive_backend_disabled,
    mark_hive_backend_disabled,
    query_dataframe,
)

logger = logging.getLogger(__name__)


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df = df.copy()
    df.columns = [str(c).split(".")[-1].lower() for c in df.columns]
    return df


def _sanitize_category_revenue_df(df: pd.DataFrame) -> pd.DataFrame:
    """去掉 NULL/NaN 成交额，避免 ECharts 显示「无效数据」。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=["category", "revenue"])
    d = _norm_cols(df.copy())
    if "category" not in d.columns or "revenue" not in d.columns:
        return pd.DataFrame(columns=["category", "revenue"])
    out = pd.DataFrame(
        {
            "category": d["category"]
            .astype(str)
            .str.strip()
            .replace({"nan": "未命名", "none": "未命名", "<na>": "未命名"})
            .fillna("未命名"),
            "revenue": pd.to_numeric(d["revenue"], errors="coerce").fillna(0.0).clip(lower=0),
        }
    )
    out = out.groupby("category", as_index=False)["revenue"].sum()
    out = out[out["revenue"] > 0].sort_values("revenue", ascending=False).reset_index(drop=True)
    return out

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "docs" / "data"
_HIVE_TABLE_CACHE: dict[str, pd.DataFrame] = {}

# 行为统一映射（与 docs/hive/data_cleaning.sql 一致）
BEHAVIOR_CASE = """
    CASE
        WHEN behavior_type IN ('pv', '浏览') THEN 'pv'
        WHEN behavior_type IN ('click', '点击') THEN 'click'
        WHEN behavior_type IN ('cart', '加购') THEN 'cart'
        WHEN behavior_type IN ('fav', '收藏') THEN 'fav'
        WHEN behavior_type IN ('buy', '购买') THEN 'buy'
        ELSE behavior_type
    END
"""

# user_behavior_2025 在部分环境中为英文，部分为中文或大写，需单独规范化
UB25_BEHAVIOR = """
    CASE
        WHEN UPPER(TRIM(CAST(behavior_type AS STRING))) IN ('PV') THEN 'pv'
        WHEN TRIM(CAST(behavior_type AS STRING)) IN ('pv', '浏览') THEN 'pv'
        WHEN TRIM(CAST(behavior_type AS STRING)) IN ('click', '点击') THEN 'click'
        WHEN TRIM(CAST(behavior_type AS STRING)) IN ('cart', '加购') THEN 'cart'
        WHEN TRIM(CAST(behavior_type AS STRING)) IN ('fav', '收藏') THEN 'fav'
        WHEN TRIM(CAST(behavior_type AS STRING)) IN ('buy', '购买') THEN 'buy'
        ELSE LOWER(TRIM(CAST(behavior_type AS STRING)))
    END
"""

SQL_DAILY_PV_UV = f"""
WITH norm AS (
    SELECT user_id, {BEHAVIOR_CASE} AS bt, CAST(behavior_time AS TIMESTAMP) AS ts
    FROM user_behaviors
    WHERE user_id IS NOT NULL AND behavior_time IS NOT NULL
)
SELECT date_format(ts, 'yyyy-MM-dd') AS d,
       SUM(CASE WHEN bt = 'pv' THEN 1 ELSE 0 END) AS pv,
       COUNT(DISTINCT CASE WHEN bt = 'pv' THEN user_id END) AS uv
FROM norm
GROUP BY date_format(ts, 'yyyy-MM-dd')
ORDER BY d
"""

SQL_HOURLY_PV = f"""
WITH norm AS (
    SELECT user_id, {BEHAVIOR_CASE} AS bt, CAST(behavior_time AS TIMESTAMP) AS ts
    FROM user_behaviors
    WHERE user_id IS NOT NULL AND behavior_time IS NOT NULL
)
SELECT hour(ts) AS hr, COUNT(*) AS pv
FROM norm
WHERE bt = 'pv'
GROUP BY hour(ts)
ORDER BY hr
"""

SQL_HEATMAP = f"""
WITH norm AS (
    SELECT user_id, {BEHAVIOR_CASE} AS bt, CAST(behavior_time AS TIMESTAMP) AS ts
    FROM user_behaviors
    WHERE user_id IS NOT NULL AND behavior_time IS NOT NULL
)
SELECT CAST(date_format(ts, 'u') AS INT) AS weekday,
       hour(ts) AS hr,
       COUNT(*) AS cnt
FROM norm
WHERE bt = 'pv'
GROUP BY CAST(date_format(ts, 'u') AS INT), hour(ts)
"""

SQL_CATEGORY = """
SELECT COALESCE(CAST(p.category AS STRING), '未关联商品表') AS category,
       COUNT(o.order_id) AS order_cnt,
       SUM(CAST(o.actual_payment AS DOUBLE)) AS revenue
FROM orders o
LEFT JOIN products p
  ON TRIM(CAST(o.product_id AS STRING)) = TRIM(CAST(p.product_id AS STRING))
WHERE o.actual_payment IS NOT NULL
  AND TRIM(CAST(o.actual_payment AS STRING)) <> ''
GROUP BY COALESCE(CAST(p.category AS STRING), '未关联商品表')
ORDER BY revenue DESC
LIMIT 12
"""

# 仅在「有过 pv」的用户中统计后续行为，保证漏斗层级单调（购买人数 ≤ 浏览人数）
SQL_FUNNEL = f"""
WITH base AS (
    SELECT user_id, {UB25_BEHAVIOR} AS bt
    FROM user_behavior_2025
    WHERE user_id IS NOT NULL AND TRIM(CAST(user_id AS STRING)) <> ''
),
flags AS (
    SELECT user_id,
           MAX(CASE WHEN bt = 'pv' THEN 1 ELSE 0 END) AS has_pv,
           MAX(CASE WHEN bt = 'click' THEN 1 ELSE 0 END) AS has_click,
           MAX(CASE WHEN bt = 'fav' THEN 1 ELSE 0 END) AS has_fav,
           MAX(CASE WHEN bt = 'cart' THEN 1 ELSE 0 END) AS has_cart,
           MAX(CASE WHEN bt = 'buy' THEN 1 ELSE 0 END) AS has_buy
    FROM base
    GROUP BY user_id
),
agg AS (
    SELECT
        SUM(has_pv) AS pv_users,
        SUM(CASE WHEN has_pv = 1 AND has_click = 1 THEN 1 ELSE 0 END) AS click_users,
        SUM(CASE WHEN has_pv = 1 AND has_fav = 1 THEN 1 ELSE 0 END) AS fav_users,
        SUM(CASE WHEN has_pv = 1 AND has_cart = 1 THEN 1 ELSE 0 END) AS cart_users,
        SUM(CASE WHEN has_pv = 1 AND has_buy = 1 THEN 1 ELSE 0 END) AS buy_users
    FROM flags
)
SELECT pv_users, click_users, fav_users, cart_users, buy_users,
       click_users * 1.0 / NULLIF(pv_users, 0) AS pv_to_click_rate,
       buy_users * 1.0 / NULLIF(pv_users, 0) AS overall_conversion_rate
FROM agg
"""

SQL_TOP_CONV = f"""
WITH ub AS (
    SELECT TRIM(CAST(product_id AS STRING)) AS product_id,
           user_id,
           {UB25_BEHAVIOR} AS bt
    FROM user_behavior_2025
    WHERE user_id IS NOT NULL
),
per_user AS (
    SELECT product_id,
           user_id,
           MAX(CASE WHEN bt = 'pv' THEN 1 ELSE 0 END) AS had_pv,
           MAX(CASE WHEN bt = 'buy' THEN 1 ELSE 0 END) AS had_buy
    FROM ub
    GROUP BY product_id, user_id
),
behavior_stats AS (
    SELECT product_id,
           SUM(had_pv) AS pv_count,
           SUM(CASE WHEN had_pv = 1 AND had_buy = 1 THEN 1 ELSE 0 END) AS buy_count
    FROM per_user
    GROUP BY product_id
)
SELECT product_id, pv_count, buy_count,
       CAST(buy_count AS DOUBLE) / NULLIF(CAST(pv_count AS DOUBLE), 0) AS conversion_rate
FROM behavior_stats
WHERE pv_count >= 3 AND buy_count >= 1
ORDER BY conversion_rate DESC, buy_count DESC, pv_count DESC
LIMIT 15
"""

SQL_TOP_CONV_LOOSE = f"""
WITH ub AS (
    SELECT TRIM(CAST(product_id AS STRING)) AS product_id,
           user_id,
           {UB25_BEHAVIOR} AS bt
    FROM user_behavior_2025
    WHERE user_id IS NOT NULL
),
per_user AS (
    SELECT product_id,
           user_id,
           MAX(CASE WHEN bt = 'pv' THEN 1 ELSE 0 END) AS had_pv,
           MAX(CASE WHEN bt = 'buy' THEN 1 ELSE 0 END) AS had_buy
    FROM ub
    GROUP BY product_id, user_id
),
behavior_stats AS (
    SELECT product_id,
           SUM(had_pv) AS pv_count,
           SUM(CASE WHEN had_pv = 1 AND had_buy = 1 THEN 1 ELSE 0 END) AS buy_count
    FROM per_user
    GROUP BY product_id
)
SELECT product_id, pv_count, buy_count,
       CAST(buy_count AS DOUBLE) / NULLIF(CAST(pv_count AS DOUBLE), 0) AS conversion_rate
FROM behavior_stats
WHERE pv_count >= 5
ORDER BY conversion_rate DESC, buy_count DESC, pv_count DESC
LIMIT 15
"""

# 云上 user_behavior_2025 为空或与脚本字段不一致时，用 user_behaviors 兜底
SQL_FUNNEL_FROM_USER_BEHAVIORS = f"""
WITH norm AS (
    SELECT user_id, {BEHAVIOR_CASE} AS bt
    FROM user_behaviors
    WHERE user_id IS NOT NULL
),
flags AS (
    SELECT user_id,
           MAX(CASE WHEN bt = 'pv' THEN 1 ELSE 0 END) AS has_pv,
           MAX(CASE WHEN bt = 'click' THEN 1 ELSE 0 END) AS has_click,
           MAX(CASE WHEN bt = 'fav' THEN 1 ELSE 0 END) AS has_fav,
           MAX(CASE WHEN bt = 'cart' THEN 1 ELSE 0 END) AS has_cart,
           MAX(CASE WHEN bt = 'buy' THEN 1 ELSE 0 END) AS has_buy
    FROM norm
    GROUP BY user_id
),
agg AS (
    SELECT
        SUM(has_pv) AS pv_users,
        SUM(CASE WHEN has_pv = 1 AND has_click = 1 THEN 1 ELSE 0 END) AS click_users,
        SUM(CASE WHEN has_pv = 1 AND has_fav = 1 THEN 1 ELSE 0 END) AS fav_users,
        SUM(CASE WHEN has_pv = 1 AND has_cart = 1 THEN 1 ELSE 0 END) AS cart_users,
        SUM(CASE WHEN has_pv = 1 AND has_buy = 1 THEN 1 ELSE 0 END) AS buy_users
    FROM flags
)
SELECT pv_users, click_users, fav_users, cart_users, buy_users,
       click_users * 1.0 / NULLIF(pv_users, 0) AS pv_to_click_rate,
       buy_users * 1.0 / NULLIF(pv_users, 0) AS overall_conversion_rate
FROM agg
"""

SQL_TOP_CONV_FROM_USER_BEHAVIORS = f"""
WITH norm AS (
    SELECT TRIM(CAST(product_id AS STRING)) AS product_id,
           user_id,
           {BEHAVIOR_CASE} AS bt
    FROM user_behaviors
    WHERE product_id IS NOT NULL AND user_id IS NOT NULL
),
per_user AS (
    SELECT product_id,
           user_id,
           MAX(CASE WHEN bt = 'pv' THEN 1 ELSE 0 END) AS had_pv,
           MAX(CASE WHEN bt = 'buy' THEN 1 ELSE 0 END) AS had_buy
    FROM norm
    GROUP BY product_id, user_id
),
behavior_stats AS (
    SELECT product_id,
           SUM(had_pv) AS pv_count,
           SUM(CASE WHEN had_pv = 1 AND had_buy = 1 THEN 1 ELSE 0 END) AS buy_count
    FROM per_user
    GROUP BY product_id
)
SELECT product_id, pv_count, buy_count,
       CAST(buy_count AS DOUBLE) / NULLIF(CAST(pv_count AS DOUBLE), 0) AS conversion_rate
FROM behavior_stats
WHERE pv_count >= 3 AND buy_count >= 1
ORDER BY conversion_rate DESC, buy_count DESC, pv_count DESC
LIMIT 15
"""

SQL_TOP_CONV_FROM_USER_BEHAVIORS_LOOSE = f"""
WITH norm AS (
    SELECT TRIM(CAST(product_id AS STRING)) AS product_id,
           user_id,
           {BEHAVIOR_CASE} AS bt
    FROM user_behaviors
    WHERE product_id IS NOT NULL AND user_id IS NOT NULL
),
per_user AS (
    SELECT product_id,
           user_id,
           MAX(CASE WHEN bt = 'pv' THEN 1 ELSE 0 END) AS had_pv,
           MAX(CASE WHEN bt = 'buy' THEN 1 ELSE 0 END) AS had_buy
    FROM norm
    GROUP BY product_id, user_id
),
behavior_stats AS (
    SELECT product_id,
           SUM(had_pv) AS pv_count,
           SUM(CASE WHEN had_pv = 1 AND had_buy = 1 THEN 1 ELSE 0 END) AS buy_count
    FROM per_user
    GROUP BY product_id
)
SELECT product_id, pv_count, buy_count,
       CAST(buy_count AS DOUBLE) / NULLIF(CAST(pv_count AS DOUBLE), 0) AS conversion_rate
FROM behavior_stats
WHERE pv_count >= 5
ORDER BY conversion_rate DESC, buy_count DESC, pv_count DESC
LIMIT 15
"""

SQL_RFM = """
WITH rfm_base AS (
    SELECT user_id,
           MAX(CAST(order_date AS TIMESTAMP)) AS last_order_ts,
           COUNT(*) AS frequency,
           SUM(CAST(actual_payment AS DOUBLE)) AS monetary
    FROM orders
    WHERE actual_payment IS NOT NULL
      AND TRIM(CAST(actual_payment AS STRING)) <> ''
    GROUP BY user_id
),
rfm_score AS (
    SELECT user_id, frequency, monetary,
           DATEDIFF(CURRENT_DATE, CAST(last_order_ts AS DATE)) AS recency,
           NTILE(5) OVER (ORDER BY DATEDIFF(CURRENT_DATE, CAST(last_order_ts AS DATE)) DESC) AS r_score,
           NTILE(5) OVER (ORDER BY frequency) AS f_score,
           NTILE(5) OVER (ORDER BY monetary) AS m_score
    FROM rfm_base
),
rfm_label AS (
    SELECT user_id, r_score, f_score, m_score,
           CASE
               WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN '高价值用户'
               WHEN r_score >= 3 AND f_score >= 3 THEN '潜力用户'
               WHEN r_score <= 2 AND f_score <= 2 THEN '流失风险用户'
               ELSE '一般用户'
           END AS user_segment
    FROM rfm_score
)
SELECT user_segment, COUNT(*) AS user_count
FROM rfm_label
GROUP BY user_segment
"""

# 不依赖 NTILE 窗口函数，兼容老版本 Hive / 避免日期解析导致整段失败
SQL_RFM_BUCKETS = """
WITH rfm_base AS (
    SELECT user_id,
           MAX(CAST(order_date AS TIMESTAMP)) AS last_order_ts,
           COUNT(*) AS frequency,
           SUM(CAST(actual_payment AS DOUBLE)) AS monetary
    FROM orders
    WHERE actual_payment IS NOT NULL
      AND TRIM(CAST(actual_payment AS STRING)) <> ''
    GROUP BY user_id
),
labeled AS (
    SELECT user_id,
           DATEDIFF(CURRENT_DATE, CAST(last_order_ts AS DATE)) AS recency_days,
           frequency,
           monetary,
           CASE
               WHEN DATEDIFF(CURRENT_DATE, CAST(last_order_ts AS DATE)) <= 120
                    AND frequency >= 3 AND monetary >= 1500 THEN '高价值用户'
               WHEN DATEDIFF(CURRENT_DATE, CAST(last_order_ts AS DATE)) <= 200 AND frequency >= 2 THEN '潜力用户'
               WHEN DATEDIFF(CURRENT_DATE, CAST(last_order_ts AS DATE)) > 300 OR frequency <= 1 THEN '流失风险用户'
               ELSE '一般用户'
           END AS user_segment
    FROM rfm_base
)
SELECT user_segment, COUNT(*) AS user_count
FROM labeled
GROUP BY user_segment
"""


def _load_local_behaviors() -> pd.DataFrame:
    path = DATA_DIR / "user_behaviors.csv"
    df = pd.read_csv(path)
    bt_map = {
        "浏览": "pv",
        "点击": "click",
        "加购": "cart",
        "收藏": "fav",
        "购买": "buy",
    }
    df["bt"] = df["behavior_type"].map(lambda x: bt_map.get(x, x))
    df["ts"] = pd.to_datetime(df["behavior_time"])
    return df


def _load_local_user_behavior_2025() -> pd.DataFrame:
    path = DATA_DIR / "UserBehavior_2025.csv"
    df = pd.read_csv(path)
    df.columns = [
        "user_id",
        "product_id",
        "brand",
        "brand_id",
        "product_name",
        "category",
        "category_id",
        "behavior_type",
        "ts",
        "price",
    ]
    df["user_id"] = df["user_id"].astype(str)
    return df


def _load_local_orders_products() -> tuple[pd.DataFrame, pd.DataFrame]:
    orders = pd.read_csv(DATA_DIR / "orders.csv")
    products = pd.read_csv(DATA_DIR / "products.csv")
    return orders, products


def _load_hive_table(conn, table_name: str) -> pd.DataFrame:
    cached = _HIVE_TABLE_CACHE.get(table_name)
    if cached is not None:
        return cached.copy()
    df = _norm_cols(query_dataframe(conn, f"SELECT * FROM {table_name}"))
    _HIVE_TABLE_CACHE[table_name] = df.copy()
    return df


def _load_hive_behaviors(conn) -> pd.DataFrame:
    df = _load_hive_table(conn, "user_behaviors")
    bt_map = {
        "浏览": "pv",
        "点击": "click",
        "加购": "cart",
        "收藏": "fav",
        "购买": "buy",
    }
    out = df.copy()
    out["behavior_type"] = out["behavior_type"].astype(str).str.strip()
    out["bt"] = out["behavior_type"].map(lambda x: bt_map.get(x, x.lower()))
    out["ts"] = pd.to_datetime(out["behavior_time"], errors="coerce")
    return out


def _load_hive_user_behavior_2025(conn) -> pd.DataFrame:
    df = _load_hive_table(conn, "user_behavior_2025").copy()
    expected = [
        "user_id",
        "product_id",
        "brand",
        "brand_id",
        "product_name",
        "category",
        "category_id",
        "behavior_type",
        "ts",
        "price",
    ]
    if len(df.columns) == 10 and list(df.columns) != expected:
        df.columns = expected
    df["user_id"] = df["user_id"].astype(str)
    return df


def _load_hive_orders_products(conn) -> tuple[pd.DataFrame, pd.DataFrame]:
    orders = _load_hive_table(conn, "orders").copy()
    products = _load_hive_table(conn, "products").copy()
    return orders, products


def _df_daily_pv_uv(df: pd.DataFrame) -> pd.DataFrame:
    sub = df[df["bt"] == "pv"].copy()
    sub["d"] = sub["ts"].dt.strftime("%Y-%m-%d")
    g = sub.groupby("d").agg(pv=("user_id", "size"), uv=("user_id", "nunique")).reset_index()
    return g.sort_values("d")


def _df_hourly(df: pd.DataFrame) -> pd.DataFrame:
    sub = df[df["bt"] == "pv"].copy()
    sub["hr"] = sub["ts"].dt.hour
    return sub.groupby("hr").size().reset_index(name="pv").sort_values("hr")


def _df_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    sub = df[df["bt"] == "pv"].copy()
    sub["weekday"] = sub["ts"].dt.dayofweek + 1
    sub["hr"] = sub["ts"].dt.hour
    return sub.groupby(["weekday", "hr"]).size().reset_index(name="cnt")


def _df_category(orders: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    m = orders.merge(products, on="product_id", how="inner")
    m["actual_payment"] = pd.to_numeric(m["actual_payment"], errors="coerce")
    m = m[m["actual_payment"].notna()]
    g = (
        m.groupby("category")
        .agg(order_cnt=("order_id", "count"), revenue=("actual_payment", "sum"))
        .reset_index()
        .sort_values("revenue", ascending=False)
        .head(12)
    )
    return g


def _df_funnel(df: pd.DataFrame) -> pd.DataFrame:
    """仅在「有过 pv」的用户中统计后续行为，与 Hive SQL_FUNNEL 口径一致。"""
    d = df.dropna(subset=["user_id"]).copy()
    d["behavior_type"] = d["behavior_type"].astype(str).str.strip().str.lower()
    bt_sets = d.groupby("user_id")["behavior_type"].apply(lambda s: set(s.unique())).reset_index(name="bt")
    pv_u = int(bt_sets["bt"].map(lambda s: "pv" in s).sum())
    click_u = int(bt_sets["bt"].map(lambda s: "pv" in s and "click" in s).sum())
    fav_u = int(bt_sets["bt"].map(lambda s: "pv" in s and "fav" in s).sum())
    cart_u = int(bt_sets["bt"].map(lambda s: "pv" in s and "cart" in s).sum())
    buy_u = int(bt_sets["bt"].map(lambda s: "pv" in s and "buy" in s).sum())
    rows = {
        "pv_users": pv_u,
        "click_users": click_u,
        "fav_users": fav_u,
        "cart_users": cart_u,
        "buy_users": buy_u,
        "overall_conversion_rate": (buy_u / pv_u) if pv_u else 0.0,
        "pv_to_click_rate": (click_u / pv_u) if pv_u else 0.0,
    }
    return pd.DataFrame([rows])


def _df_top_conv(df: pd.DataFrame) -> pd.DataFrame:
    """浏览→购买转化率：分母为「该商品有过 pv 的去重用户」，分子为其中也出现过 buy 的用户（同人同品）。"""
    d = df.dropna(subset=["product_id", "user_id"]).copy()
    bt_map = {
        "浏览": "pv",
        "点击": "click",
        "加购": "cart",
        "收藏": "fav",
        "购买": "buy",
    }
    raw_bt = d["behavior_type"].astype(str).str.strip()
    d["bt"] = raw_bt.str.lower().map(lambda x: bt_map.get(x, x))
    du = d[d["bt"].isin(["pv", "buy"])].drop_duplicates(subset=["product_id", "user_id", "bt"])
    per = (
        du.groupby(["product_id", "user_id"])["bt"]
        .apply(lambda s: set(s.tolist()))
        .reset_index(name="bts")
    )
    per["had_pv"] = per["bts"].map(lambda s: "pv" in s)
    per["had_buy"] = per["bts"].map(lambda s: "buy" in s)
    per["browse_and_buy"] = per["had_pv"] & per["had_buy"]
    m = per.groupby("product_id", as_index=False).agg(
        pv_count=("had_pv", "sum"),
        buy_count=("browse_and_buy", "sum"),
    )
    m["buy_count"] = m["buy_count"].astype(int)
    raw = m["buy_count"] / m["pv_count"].replace(0, float("nan"))
    m["conversion_rate"] = raw.clip(upper=1.0)
    strict = m[(m["pv_count"] >= 3) & (m["buy_count"] >= 1)].sort_values(
        ["conversion_rate", "buy_count", "pv_count"], ascending=[False, False, False]
    )
    if len(strict) > 0:
        return strict.head(15)
    loose = m[m["pv_count"] >= 5].sort_values(
        ["conversion_rate", "buy_count", "pv_count"], ascending=[False, False, False]
    )
    return loose.head(15)


def _df_rfm(orders: pd.DataFrame) -> pd.DataFrame:
    """与 Hive NTILE 口径近似：R 越小越近（分越高），F/M 越大分越高。"""
    o = orders.copy()
    o["actual_payment"] = pd.to_numeric(o["actual_payment"], errors="coerce")
    o = o[o["actual_payment"].notna()].copy()
    o["order_date"] = pd.to_datetime(o["order_date"])
    ref = o["order_date"].max()
    g = o.groupby("user_id").agg(
        last_order_date=("order_date", "max"),
        frequency=("order_id", "count"),
        monetary=("actual_payment", "sum"),
    )
    g["recency"] = (ref - g["last_order_date"]).dt.days

    def q5(s: pd.Series, labels: list[int]) -> pd.Series:
        try:
            return pd.qcut(s, q=5, labels=labels, duplicates="drop").astype(float)
        except ValueError:
            return pd.Series([3.0] * len(s), index=s.index)

    g["r_score"] = q5(g["recency"], [5, 4, 3, 2, 1])
    g["f_score"] = q5(g["frequency"], [1, 2, 3, 4, 5])
    g["m_score"] = q5(g["monetary"], [1, 2, 3, 4, 5])

    def seg(row):
        r, f, m = row["r_score"], row["f_score"], row["m_score"]
        if pd.isna(r) or pd.isna(f) or pd.isna(m):
            return "一般用户"
        r, f, m = int(r), int(f), int(m)
        if r >= 4 and f >= 4 and m >= 4:
            return "高价值用户"
        if r >= 3 and f >= 3:
            return "潜力用户"
        if r <= 2 and f <= 2:
            return "流失风险用户"
        return "一般用户"

    g["user_segment"] = g.apply(seg, axis=1)
    return g.groupby("user_segment").size().reset_index(name="user_count")


def _run_sql(conn, sql: str) -> pd.DataFrame:
    return _norm_cols(query_dataframe(conn, sql))


def _run_sql_safe(conn, sql: str, label: str) -> pd.DataFrame:
    """单条 Hive 查询失败时返回空表并打日志，避免一条 SQL 拖垮整个看板。"""
    try:
        return _run_sql(conn, sql)
    except Exception as exc:
        mark_hive_backend_disabled(f"{label}: {exc}")
        return pd.DataFrame()


def _funnel_pv_users(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    try:
        v = df.iloc[0].get("pv_users", 0)
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _chart_line_pv_uv(df: pd.DataFrame) -> str:
    if df.empty:
        df = pd.DataFrame({"d": ["N/A"], "pv": [0], "uv": [0]})
    line = (
        Line(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add_xaxis(df["d"].astype(str).tolist())
        .add_yaxis("PV", df["pv"].astype(float).round(0).tolist(), label_opts=opts.LabelOpts(is_show=True))
        .add_yaxis("UV", df["uv"].astype(float).round(0).tolist(), label_opts=opts.LabelOpts(is_show=True))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="日粒度 PV / UV 趋势", subtitle="页面浏览量与独立访客"),
            xaxis_opts=opts.AxisOpts(name="日期", name_location="middle", name_gap=30),
            yaxis_opts=opts.AxisOpts(name="次数 / 人数"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            datazoom_opts=[opts.DataZoomOpts()],
        )
    )
    return line.dump_options_with_quotes()


def _chart_bar_hourly(df: pd.DataFrame) -> str:
    if df.empty:
        df = pd.DataFrame({"hr": [0], "pv": [0]})
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add_xaxis([f"{int(h)}时" for h in df["hr"]])
        .add_yaxis("PV", df["pv"].astype(float).tolist(), label_opts=opts.LabelOpts(is_show=True))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="24 小时 PV 分布", subtitle="识别访问高峰时段"),
            xaxis_opts=opts.AxisOpts(name="小时", name_location="middle", name_gap=30),
            yaxis_opts=opts.AxisOpts(name="PV"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_bar_category(df: pd.DataFrame) -> str:
    clean = _sanitize_category_revenue_df(df)
    if clean.empty:
        clean = pd.DataFrame({"category": ["无有效品类数据"], "revenue": [0.0]})
    # 横向条形图默认「类目轴第一项在下方」：反转为升序后，成交额最高的品类出现在最上方
    disp = clean.iloc[::-1].reset_index(drop=True)
    rev = [float(round(float(x), 2)) for x in disp["revenue"]]
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add_xaxis(disp["category"].astype(str).tolist())
        .add_yaxis(
            "成交额",
            rev,
            label_opts=opts.LabelOpts(is_show=True, formatter="{c}"),
        )
        .reversal_axis()
        .set_series_opts(label_opts=opts.LabelOpts(position="right"))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="品类成交额 TOP", subtitle="按成交额从高到低排序（自上而下）"),
            xaxis_opts=opts.AxisOpts(name="成交额（元）"),
            yaxis_opts=opts.AxisOpts(name="品类"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_heatmap(df: pd.DataFrame) -> str:
    df = _norm_cols(df)
    if df.empty:
        df = pd.DataFrame({"weekday": [1], "hr": [0], "cnt": [0]})
    wlabels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    hours = list(range(24))
    data_map = {}
    for _, row in df.iterrows():
        data_map[(int(row["weekday"]), int(row["hr"]))] = int(row["cnt"])
    data = []
    max_v = 1
    for wi in range(1, 8):
        for hi in hours:
            v = data_map.get((wi, hi), 0)
            max_v = max(max_v, v)
            data.append([hi, wi - 1, v])
    hm = (
        HeatMap(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="480px"))
        .add_xaxis([f"{h}时" for h in hours])
        .add_yaxis(
            "星期",
            wlabels,
            data,
            # 不在格子里堆数字；options 经 json.loads 传给前端时 JsCode 会变成字符串被当成文本画出
            label_opts=opts.LabelOpts(is_show=False),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(title="PV 热力图（星期 × 小时）", subtitle="颜色越深访问越集中；悬浮查看具体 PV"),
            visualmap_opts=opts.VisualMapOpts(min_=0, max_=max(max_v, 1), pos_top="middle"),
            tooltip_opts=opts.TooltipOpts(trigger="item"),
            xaxis_opts=opts.AxisOpts(name="小时"),
            yaxis_opts=opts.AxisOpts(name="星期"),
        )
    )
    return hm.dump_options_with_quotes()


def _chart_funnel(row: Optional[pd.Series]) -> str:
    if row is None:
        row = pd.Series(dtype=float)
    stages = [
        ("浏览(pv)", float(row.get("pv_users", 0) or 0)),
        ("点击(click)", float(row.get("click_users", 0) or 0)),
        ("收藏(fav)", float(row.get("fav_users", 0) or 0)),
        ("加购(cart)", float(row.get("cart_users", 0) or 0)),
        ("购买(buy)", float(row.get("buy_users", 0) or 0)),
    ]
    data = [{"name": n, "value": v} for n, v in stages if v > 0]
    if not data:
        data = [{"name": "无数据", "value": 1}]
    funnel = (
        Funnel(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="460px"))
        .add(
            series_name="转化",
            data_pair=[(d["name"], d["value"]) for d in data],
            label_opts=opts.LabelOpts(position="inside", formatter="{b}: {c}"),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="用户行为漏斗（独立访客）",
                subtitle="仅在「有过浏览(pv)」的用户中统计后续行为，保证层级单调递减",
            ),
            tooltip_opts=opts.TooltipOpts(trigger="item", formatter="{b}: {c}"),
        )
    )
    return funnel.dump_options_with_quotes()


def _chart_bar_conversion(df: pd.DataFrame) -> str:
    if df.empty:
        df = pd.DataFrame({"product_id": ["—"], "conversion_rate": [0.0]})
    else:
        df = df.copy()
        df["conversion_rate"] = pd.to_numeric(df["conversion_rate"], errors="coerce").fillna(0.0).clip(upper=1.0)
        df["product_id"] = df["product_id"].astype(str)
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add_xaxis(df["product_id"].tolist())
        .add_yaxis(
            "转化率",
            [round(min(float(x), 1.0) * 100, 2) for x in df["conversion_rate"]],
            label_opts=opts.LabelOpts(is_show=True, formatter="{c}%"),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="商品浏览-购买转化率 TOP（用户去重）",
                subtitle="每商品：在「有浏览」用户中，同时也有购买的人数 ÷ 浏览用户数；"
                "严格：浏览用户≥3 且转化用户≥1，否则放宽为浏览用户≥5",
            ),
            xaxis_opts=opts.AxisOpts(name="商品ID", axislabel_opts=opts.LabelOpts(rotate=45)),
            yaxis_opts=opts.AxisOpts(name="转化率（%）", max_=100),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_pie_rfm(df: pd.DataFrame) -> str:
    if df.empty:
        df = pd.DataFrame({"user_segment": ["无数据"], "user_count": [1]})
    else:
        df = df.copy()
        df["user_count"] = pd.to_numeric(df["user_count"], errors="coerce").fillna(0.0)
        df["user_segment"] = df["user_segment"].astype(str)
        df = df[df["user_count"] > 0]
        if df.empty:
            df = pd.DataFrame({"user_segment": ["无数据"], "user_count": [1]})
    pie = (
        Pie(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="440px"))
        .add(
            series_name="用户分层",
            data_pair=[list(z) for z in zip(df["user_segment"].tolist(), df["user_count"].astype(float).tolist())],
            radius=["35%", "60%"],
            label_opts=opts.LabelOpts(formatter="{b}: {c} ({d}%)"),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(title="RFM 用户价值分层", subtitle="基于订单频次与金额分位数"),
            legend_opts=opts.LegendOpts(orient="vertical", pos_left="left", type_="scroll"),
            tooltip_opts=opts.TooltipOpts(trigger="item"),
        )
    )
    return pie.dump_options_with_quotes()


def build_conclusions(
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    category: pd.DataFrame,
    heatmap: pd.DataFrame,
    funnel_row: Optional[pd.Series],
    conv: pd.DataFrame,
    rfm: pd.DataFrame,
) -> dict[str, str]:
    out: dict[str, str] = {}
    if not daily.empty:
        peak_day = daily.loc[daily["pv"].idxmax()]
        out["behavior"] = (
            f"观测期内 PV 最高日为 {peak_day['d']}（PV={int(peak_day['pv'])}，UV={int(peak_day['uv'])}）。"
            "PV/UV 比可反映人均访问深度，便于评估活动拉新后的回访情况。"
        )
    else:
        out["behavior"] = "暂无可用的行为日粒度数据。"

    if not hourly.empty:
        peak_h = int(hourly.loc[hourly["pv"].idxmax()]["hr"])
        out["time"] = (
            f"按小时统计的浏览高峰约在 {peak_h}:00–{peak_h + 1}:00，可在该时段加大投放与客服资源。"
            "热力图进一步展示工作日与周末的差异，用于排班与促销节奏。"
        )
    else:
        out["time"] = "暂无可用的小时分布数据。"

    if not category.empty:
        cc = _norm_cols(category.copy())
        if "category" in cc.columns and "revenue" in cc.columns:
            cc["_rev"] = pd.to_numeric(cc["revenue"], errors="coerce").fillna(0.0)
            top = cc.sort_values("_rev", ascending=False).iloc[0]
            rev = float(top["_rev"])
        else:
            top = cc.iloc[0]
            rev = float(pd.to_numeric(top.get("revenue", 0), errors="coerce") or 0)
        out["product"] = (
            f"成交额最高的品类为「{top['category']}」，累计实付约 {rev:,.2f} 元。"
            "结合商品转化率榜单，可优先在热销品类中复制高转化单品运营策略。"
        )
    else:
        out["product"] = "暂无可用的品类订单数据。"

    if funnel_row is not None and len(funnel_row) > 0:
        pv_u = float(funnel_row.get("pv_users", 0) or 0)
        buy_u = float(funnel_row.get("buy_users", 0) or 0)
        overall_raw = float(funnel_row.get("overall_conversion_rate", 0) or 0) if pv_u else 0.0
        if buy_u > pv_u or overall_raw > 1.0:
            out["funnel"] = (
                "漏斗人数关系异常（购买>浏览或比率>100%），请检查上游数据；"
                "当前展示口径为「有浏览用户中的各行为人数」。"
            )
        else:
            overall = min(overall_raw, 1.0)
            out["funnel"] = (
                f"漏斗口径：仅在「有过浏览(pv)」的用户中统计后续行为去重人数，各层不超过浏览用户数。"
                f"浏览用户中发生过购买的比例整体约 {overall * 100:.2f}%，可对照点击/收藏/加购定位流失环节。"
            )
    else:
        out["funnel"] = "暂无可用的漏斗数据。"

    if not conv.empty:
        top_rate = min(float(conv.iloc[0]["conversion_rate"]), 1.0) * 100
        out["conversion"] = (
            f"商品维度按「有浏览用户中，同时有购买的人数 ÷ 浏览用户数」统计（同人同品，自然不超过 100%），"
            f"当前榜单最高约 {top_rate:.2f}%，可作详情页与定价的对标参考。"
        )
    else:
        out["conversion"] = "暂无可用的商品转化率数据。"

    if not rfm.empty:
        seg = rfm.sort_values("user_count", ascending=False).iloc[0]["user_segment"]
        cnt = int(rfm["user_count"].sum())
        out["rfm"] = (
            f"基于订单的 RFM 分层共覆盖 {cnt} 名有单用户，人数最多的群体为「{seg}」。"
            "高价值用户适合会员权益与专属活动，流失风险用户适合召回券与触达。"
        )
    else:
        out["rfm"] = "暂无可用的 RFM 数据。"

    return out


def get_dashboard_payload() -> dict[str, Any]:
    """供路由渲染：图表 options JSON 字符串、结论文本、数据源说明。"""
    use_local = force_local_mode() or is_hive_backend_disabled()
    conn = None if use_local else get_hive_connection()
    source = "本地 CSV（docs/data）"

    if conn is not None and not use_local:
        configure_hive_session(conn)
        daily = _run_sql_safe(conn, SQL_DAILY_PV_UV, "daily_pv_uv")
        if not is_hive_backend_disabled():
            hourly = _run_sql_safe(conn, SQL_HOURLY_PV, "hourly_pv")
        if not is_hive_backend_disabled():
            heatmap = _run_sql_safe(conn, SQL_HEATMAP, "heatmap")
        if not is_hive_backend_disabled():
            category = _norm_cols(_run_sql_safe(conn, SQL_CATEGORY, "category_revenue"))
        if not is_hive_backend_disabled():
            funnel = _run_sql_safe(conn, SQL_FUNNEL, "funnel")
            if _funnel_pv_users(funnel) == 0:
                funnel_fb = _run_sql_safe(conn, SQL_FUNNEL_FROM_USER_BEHAVIORS, "funnel_fallback_user_behaviors")
                if _funnel_pv_users(funnel_fb) > 0:
                    funnel = funnel_fb
        if not is_hive_backend_disabled():
            conv = _run_sql_safe(conn, SQL_TOP_CONV, "top_conversion")
            if conv.empty:
                conv = _run_sql_safe(conn, SQL_TOP_CONV_LOOSE, "top_conversion_loose_ub25")
            if conv.empty:
                conv = _run_sql_safe(conn, SQL_TOP_CONV_FROM_USER_BEHAVIORS, "top_conversion_user_behaviors")
            if conv.empty:
                conv = _run_sql_safe(conn, SQL_TOP_CONV_FROM_USER_BEHAVIORS_LOOSE, "top_conversion_loose_user_behaviors")
        if not is_hive_backend_disabled():
            rfm = _run_sql_safe(conn, SQL_RFM, "rfm")
            if rfm.empty:
                rfm = _run_sql_safe(conn, SQL_RFM_BUCKETS, "rfm_buckets_fallback")

        if is_hive_backend_disabled():
            conn = None
        else:
            hive_frames = (daily, hourly, heatmap, category, funnel, conv, rfm)
            if all(df is None or df.empty for df in hive_frames):
                mark_hive_backend_disabled("Hive 全部查询无结果或失败")
                conn = None
            else:
                source = "Hive（pyhive）"

    if conn is None or use_local:
        behaviors = _load_local_behaviors()
        ub25 = _load_local_user_behavior_2025()
        orders, products = _load_local_orders_products()
        daily = _df_daily_pv_uv(behaviors)
        hourly = _df_hourly(behaviors)
        heatmap = _df_heatmap(behaviors)
        category = _df_category(orders, products)
        funnel = _df_funnel(ub25)
        conv = _df_top_conv(ub25)
        rfm = _df_rfm(orders)

    funnel_row = funnel.iloc[0] if funnel is not None and len(funnel) > 0 else None

    conclusions = build_conclusions(daily, hourly, category, heatmap, funnel_row, conv, rfm)

    charts = [
        {"id": "chart_line_pv_uv", "title": "用户行为：PV / UV", "options": _chart_line_pv_uv(daily)},
        {"id": "chart_bar_hourly", "title": "时间：小时分布", "options": _chart_bar_hourly(hourly)},
        {"id": "chart_heatmap", "title": "时间：星期×小时热力", "options": _chart_heatmap(heatmap)},
        {"id": "chart_bar_category", "title": "商品：品类成交额", "options": _chart_bar_category(category)},
        {"id": "chart_funnel", "title": "行为漏斗", "options": _chart_funnel(funnel_row)},
        {"id": "chart_bar_conversion", "title": "商品转化率", "options": _chart_bar_conversion(conv)},
        {"id": "chart_pie_rfm", "title": "RFM 分层", "options": _chart_pie_rfm(rfm)},
    ]

    summary = {}
    if not daily.empty:
        summary["total_pv"] = int(daily["pv"].sum())
        summary["max_uv_day"] = int(daily["uv"].max())
    else:
        summary["total_pv"] = 0
        summary["max_uv_day"] = 0

    charts_mount = [{"id": c["id"], "title": c["title"], "options": json.loads(c["options"])} for c in charts]

    return {
        "charts": charts,
        "charts_mount": charts_mount,
        "conclusions": conclusions,
        "data_source": source,
        "summary": summary,
    }


def get_dashboard_payload() -> dict[str, Any]:
    """Render dashboard data, preferring Hive detail reads when USE_HIVE=1."""
    use_local = force_local_mode() or is_hive_backend_disabled()
    conn = None if use_local else get_hive_connection()
    source = "本地 CSV（docs/data）"

    if conn is not None and not use_local:
        try:
            configure_hive_session(conn)
            behaviors = _load_hive_behaviors(conn)
            ub25 = _load_hive_user_behavior_2025(conn)
            orders, products = _load_hive_orders_products(conn)
            daily = _df_daily_pv_uv(behaviors)
            hourly = _df_hourly(behaviors)
            heatmap = _df_heatmap(behaviors)
            category = _df_category(orders, products)
            funnel = _df_funnel(ub25)
            conv = _df_top_conv(ub25)
            rfm = _df_rfm(orders)
            source = "Hive（明细拉取 + Python 聚合）"
        except Exception as exc:
            mark_hive_backend_disabled(str(exc))
            conn = None

    if conn is None or use_local:
        behaviors = _load_local_behaviors()
        ub25 = _load_local_user_behavior_2025()
        orders, products = _load_local_orders_products()
        daily = _df_daily_pv_uv(behaviors)
        hourly = _df_hourly(behaviors)
        heatmap = _df_heatmap(behaviors)
        category = _df_category(orders, products)
        funnel = _df_funnel(ub25)
        conv = _df_top_conv(ub25)
        rfm = _df_rfm(orders)

    funnel_row = funnel.iloc[0] if funnel is not None and len(funnel) > 0 else None
    conclusions = build_conclusions(daily, hourly, category, heatmap, funnel_row, conv, rfm)
    charts = [
        {"id": "chart_line_pv_uv", "title": "用户行为：PV / UV", "options": _chart_line_pv_uv(daily)},
        {"id": "chart_bar_hourly", "title": "时间：小时分布", "options": _chart_bar_hourly(hourly)},
        {"id": "chart_heatmap", "title": "时间：星期×小时热力", "options": _chart_heatmap(heatmap)},
        {"id": "chart_bar_category", "title": "商品：品类成交额", "options": _chart_bar_category(category)},
        {"id": "chart_funnel", "title": "行为漏斗", "options": _chart_funnel(funnel_row)},
        {"id": "chart_bar_conversion", "title": "商品转化率", "options": _chart_bar_conversion(conv)},
        {"id": "chart_pie_rfm", "title": "RFM 分层", "options": _chart_pie_rfm(rfm)},
    ]
    if not daily.empty:
        summary = {"total_pv": int(daily["pv"].sum()), "max_uv_day": int(daily["uv"].max())}
    else:
        summary = {"total_pv": 0, "max_uv_day": 0}
    charts_mount = [{"id": c["id"], "title": c["title"], "options": json.loads(c["options"])} for c in charts]
    return {
        "charts": charts,
        "charts_mount": charts_mount,
        "conclusions": conclusions,
        "data_source": source,
        "summary": summary,
    }


def charts_json_for_api() -> str:
    """可选 API：返回 JSON（含图表配置）。"""
    payload = get_dashboard_payload()
    # options 已是 JSON 字符串，解析后嵌回对象便于前端一次性消费
    out_charts = []
    for c in payload["charts"]:
        out_charts.append({"id": c["id"], "title": c["title"], "options": json.loads(c["options"])})
    return json.dumps(
        {"data_source": payload["data_source"], "conclusions": payload["conclusions"], "charts": out_charts},
        ensure_ascii=False,
    )


def _load_kmeans_outputs() -> Optional[dict[str, Any]]:
    out_dir = PROJECT_ROOT / "docs" / "outputs"
    compare_path = out_dir / "kmeans_compare_k_comparison.csv"
    if compare_path.exists():
        compare_df = pd.read_csv(compare_path)
        compare_df = compare_df.sort_values("silhouette_score", ascending=False).reset_index(drop=True)
        best_k = int(compare_df.iloc[0]["k"])
        prefix = f"kmeans_compare_k{best_k}"
    else:
        summary_path = out_dir / "final_kmeans_summary.json"
        if not summary_path.exists():
            return None
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        best_k = int(summary.get("k", 4))
        compare_df = pd.DataFrame([{"k": best_k, "silhouette_score": summary.get("silhouette_score", 0.0)}])
        prefix = "final_kmeans"

    cluster_summary_path = out_dir / f"{prefix}_cluster_summary.csv"
    cross_tab_path = out_dir / f"{prefix}_rfm_vs_kmeans.csv"
    if not cluster_summary_path.exists() or not cross_tab_path.exists():
        return None

    cluster_summary = pd.read_csv(cluster_summary_path)
    cross_tab = pd.read_csv(cross_tab_path)
    best_score = float(compare_df.iloc[0]["silhouette_score"])
    return {
        "best_k": best_k,
        "best_score": best_score,
        "comparison": compare_df,
        "cluster_summary": cluster_summary,
        "cross_tab": cross_tab,
    }


def _load_ablation_outputs() -> Optional[pd.DataFrame]:
    path = PROJECT_ROOT / "docs" / "outputs" / "ablation_profile_comparison.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if df.empty:
        return None
    return df.sort_values("silhouette_score", ascending=False).reset_index(drop=True)


def _chart_kmeans_compare(df: pd.DataFrame) -> str:
    disp = df.copy()
    disp["k"] = disp["k"].astype(int).astype(str)
    disp["silhouette_pct"] = (pd.to_numeric(disp["silhouette_score"], errors="coerce").fillna(0.0) * 100).round(2)
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add_xaxis(disp["k"].tolist())
        .add_yaxis("轮廓系数(%)", disp["silhouette_pct"].tolist(), label_opts=opts.LabelOpts(is_show=True, formatter="{c}"))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="KMeans 不同 K 值对比", subtitle="轮廓系数越高，聚类区分度越好"),
            xaxis_opts=opts.AxisOpts(name="K 值"),
            yaxis_opts=opts.AxisOpts(name="轮廓系数(%)"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_kmeans_cluster_value(df: pd.DataFrame) -> str:
    disp = df.copy()
    disp["label"] = disp.apply(
        lambda row: f"C{int(row['cluster'])}-{row.get('cluster_name', '用户群')}",
        axis=1,
    )
    spend_col = "avg(total_spent)" if "avg(total_spent)" in disp.columns else "avg(log_total_spent)"
    disp["value"] = pd.to_numeric(disp[spend_col], errors="coerce").fillna(0.0).round(2)
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add_xaxis(disp["label"].tolist())
        .add_yaxis("平均累计消费", disp["value"].tolist(), label_opts=opts.LabelOpts(is_show=True, formatter="{c}"))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="KMeans 聚类消费画像", subtitle="按聚类展示平均累计消费金额"),
            xaxis_opts=opts.AxisOpts(name="聚类群体", axislabel_opts=opts.LabelOpts(rotate=20)),
            yaxis_opts=opts.AxisOpts(name="平均累计消费"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_feature_ablation(df: pd.DataFrame) -> str:
    disp = df.copy()
    disp["feature_profile"] = disp["feature_profile"].astype(str)
    disp["silhouette_pct"] = (pd.to_numeric(disp["silhouette_score"], errors="coerce").fillna(0.0) * 100).round(2)
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="440px"))
        .add_xaxis(disp["feature_profile"].tolist())
        .add_yaxis("轮廓系数(%)", disp["silhouette_pct"].tolist(), label_opts=opts.LabelOpts(is_show=True, formatter="{c}"))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="特征消融实验对比", subtitle="对比不同特征组合下的聚类效果"),
            xaxis_opts=opts.AxisOpts(name="特征方案", axislabel_opts=opts.LabelOpts(rotate=18)),
            yaxis_opts=opts.AxisOpts(name="轮廓系数(%)"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_rfm_kmeans_heatmap(df: pd.DataFrame) -> str:
    data = df.copy()
    clusters = data["cluster"].astype(str).tolist()
    label_cols = [c for c in data.columns if c != "cluster"]
    payload = []
    max_v = 1
    for yi, label in enumerate(label_cols):
        for xi, cluster in enumerate(clusters):
            v = int(pd.to_numeric(data.iloc[xi][label], errors="coerce") or 0)
            payload.append([xi, yi, v])
            max_v = max(max_v, v)
    hm = (
        HeatMap(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="460px"))
        .add_xaxis([f"Cluster {c}" for c in clusters])
        .add_yaxis("RFM标签", label_cols, payload, label_opts=opts.LabelOpts(is_show=False))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="RFM 与 KMeans 对照热力图", subtitle="颜色越深表示该聚类中该类用户越多"),
            visualmap_opts=opts.VisualMapOpts(min_=0, max_=max_v, pos_top="middle"),
            tooltip_opts=opts.TooltipOpts(trigger="item"),
            xaxis_opts=opts.AxisOpts(name="KMeans 聚类"),
            yaxis_opts=opts.AxisOpts(name="RFM 标签"),
        )
    )
    return hm.dump_options_with_quotes()


def _build_kmeans_conclusion(data: dict[str, Any]) -> str:
    cluster_summary = data["cluster_summary"].copy()
    cross_tab = data["cross_tab"].copy()
    high_col = "高价值用户" if "高价值用户" in cross_tab.columns else cross_tab.columns[-1]
    churn_col = "流失风险用户" if "流失风险用户" in cross_tab.columns else cross_tab.columns[1]
    high_cluster = int(cross_tab.loc[cross_tab[high_col].idxmax(), "cluster"])
    churn_cluster = int(cross_tab.loc[cross_tab[churn_col].idxmax(), "cluster"])
    high_name = cluster_summary.loc[cluster_summary["cluster"] == high_cluster, "cluster_name"].iloc[0]
    churn_name = cluster_summary.loc[cluster_summary["cluster"] == churn_cluster, "cluster_name"].iloc[0]
    return (
        f"KMeans 最优 K 值为 {data['best_k']}，轮廓系数约 {data['best_score']:.4f}。"
        f"其中 Cluster {high_cluster}（{high_name}）聚集了最多高价值用户，"
        f"Cluster {churn_cluster}（{churn_name}）聚集了最多流失风险用户，"
        "说明聚类结果与 RFM 规则分层在核心用户识别上具有较强一致性。"
    )


_base_get_dashboard_payload = get_dashboard_payload


def get_dashboard_payload() -> dict[str, Any]:
    payload = _base_get_dashboard_payload()
    kmeans = _load_kmeans_outputs()
    ablation = _load_ablation_outputs()
    if not kmeans:
        return payload

    extra_charts = [
        {"id": "chart_kmeans_compare", "title": "KMeans：不同 K 值对比", "options": _chart_kmeans_compare(kmeans["comparison"])},
        {"id": "chart_kmeans_value", "title": "KMeans：聚类消费画像", "options": _chart_kmeans_cluster_value(kmeans["cluster_summary"])},
        {"id": "chart_rfm_kmeans_heatmap", "title": "RFM × KMeans 对照", "options": _chart_rfm_kmeans_heatmap(kmeans["cross_tab"])},
    ]
    if ablation is not None:
        extra_charts.append(
            {"id": "chart_feature_ablation", "title": "KMeans：特征消融对比", "options": _chart_feature_ablation(ablation)}
        )
    payload["charts"] = payload["charts"] + extra_charts
    payload["charts_mount"] = [{"id": c["id"], "title": c["title"], "options": json.loads(c["options"])} for c in payload["charts"]]
    payload["conclusions"]["KMeans"] = _build_kmeans_conclusion(kmeans)
    if ablation is not None:
        best_profile = str(ablation.iloc[0]["feature_profile"])
        best_profile_score = float(ablation.iloc[0]["silhouette_score"])
        payload["conclusions"]["KMeans特征优化"] = (
            f"特征消融实验表明，最佳特征方案为 {best_profile}，"
            f"对应轮廓系数约 {best_profile_score:.4f}，说明移除部分冗余特征后聚类区分度明显提高。"
        )
    payload["summary"]["best_kmeans_k"] = kmeans["best_k"]
    payload["summary"]["best_kmeans_silhouette"] = f"{kmeans['best_score']:.4f}"
    return payload


def _load_local_users_orders() -> tuple[pd.DataFrame, pd.DataFrame]:
    users = pd.read_csv(DATA_DIR / "users.csv")
    orders = pd.read_csv(DATA_DIR / "orders.csv")
    return users, orders


def _load_hive_users_orders() -> tuple[pd.DataFrame, pd.DataFrame]:
    conn = get_hive_connection()
    if conn is None:
        raise RuntimeError("Hive connection unavailable for user portrait analysis")
    configure_hive_session(conn)
    users = _load_hive_table(conn, "users").copy()
    orders = _load_hive_table(conn, "orders").copy()
    return users, orders


def _build_user_portrait_frames(users: pd.DataFrame, orders: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    u = users.copy()
    o = orders.copy()
    u["age"] = pd.to_numeric(u["age"], errors="coerce")
    o["actual_payment"] = pd.to_numeric(o["actual_payment"], errors="coerce").fillna(0.0)
    spend = o.groupby("user_id", as_index=False).agg(total_spent=("actual_payment", "sum"))
    merged = u.merge(spend, on="user_id", how="left")
    merged["total_spent"] = pd.to_numeric(merged["total_spent"], errors="coerce").fillna(0.0)
    merged["age_group"] = pd.cut(
        merged["age"],
        bins=[0, 25, 35, 45, 60, 120],
        labels=["<=25", "26-35", "36-45", "46-60", "60+"],
        include_lowest=True,
    )

    age_df = (
        merged.groupby("age_group", observed=False)
        .agg(user_count=("user_id", "count"), avg_spent=("total_spent", "mean"))
        .reset_index()
        .dropna(subset=["age_group"])
    )
    age_df["avg_spent_k"] = (age_df["avg_spent"] / 1000).round(2)

    gender_df = (
        merged.groupby("gender", dropna=False)
        .agg(user_count=("user_id", "count"), avg_spent=("total_spent", "mean"))
        .reset_index()
    )

    city_df = (
        merged.groupby("city", dropna=False)
        .agg(user_count=("user_id", "count"), avg_spent=("total_spent", "mean"))
        .reset_index()
        .sort_values(["user_count", "avg_spent"], ascending=[False, False])
        .head(10)
    )
    city_df["avg_spent_k"] = (city_df["avg_spent"] / 1000).round(2)

    member_df = (
        merged.groupby("member_level", dropna=False)
        .agg(user_count=("user_id", "count"), avg_spent=("total_spent", "mean"))
        .reset_index()
        .sort_values(["user_count", "avg_spent"], ascending=[False, False])
    )
    member_df["avg_spent_k"] = (member_df["avg_spent"] / 1000).round(2)
    return merged, age_df, gender_df, city_df, member_df


def _chart_bar_age_profile(df: pd.DataFrame) -> str:
    disp = df.copy()
    if disp.empty:
        disp = pd.DataFrame({"age_group": ["N/A"], "user_count": [0], "avg_spent_k": [0.0]})
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add_xaxis(disp["age_group"].astype(str).tolist())
        .add_yaxis("User Count", pd.to_numeric(disp["user_count"], errors="coerce").fillna(0).astype(int).tolist(), label_opts=opts.LabelOpts(is_show=True))
        .add_yaxis("Avg Spend (k)", pd.to_numeric(disp["avg_spent_k"], errors="coerce").fillna(0.0).round(2).tolist(), label_opts=opts.LabelOpts(is_show=True))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="User Portrait: Age Group Distribution", subtitle="Count and average spending by age group"),
            xaxis_opts=opts.AxisOpts(name="Age Group"),
            yaxis_opts=opts.AxisOpts(name="Value"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_pie_gender_profile(df: pd.DataFrame) -> str:
    disp = df.copy()
    if disp.empty:
        disp = pd.DataFrame({"gender": ["N/A"], "user_count": [1]})
    pie = (
        Pie(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add(
            series_name="Gender",
            data_pair=[list(z) for z in zip(disp["gender"].astype(str).tolist(), pd.to_numeric(disp["user_count"], errors="coerce").fillna(0).tolist())],
            radius=["35%", "60%"],
            label_opts=opts.LabelOpts(formatter="{b}: {c} ({d}%)"),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(title="User Portrait: Gender Distribution", subtitle="User count by gender"),
            tooltip_opts=opts.TooltipOpts(trigger="item"),
        )
    )
    return pie.dump_options_with_quotes()


def _chart_bar_city_profile(df: pd.DataFrame) -> str:
    disp = df.copy()
    if disp.empty:
        disp = pd.DataFrame({"city": ["N/A"], "user_count": [0]})
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="440px"))
        .add_xaxis(disp["city"].astype(str).tolist())
        .add_yaxis("User Count", pd.to_numeric(disp["user_count"], errors="coerce").fillna(0).astype(int).tolist(), label_opts=opts.LabelOpts(is_show=True))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="User Portrait: Top Cities", subtitle="Top 10 cities by user count"),
            xaxis_opts=opts.AxisOpts(name="City", axislabel_opts=opts.LabelOpts(rotate=25)),
            yaxis_opts=opts.AxisOpts(name="User Count"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_bar_member_profile(df: pd.DataFrame) -> str:
    disp = df.copy()
    if disp.empty:
        disp = pd.DataFrame({"member_level": ["N/A"], "user_count": [0], "avg_spent_k": [0.0]})
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add_xaxis(disp["member_level"].astype(str).tolist())
        .add_yaxis("User Count", pd.to_numeric(disp["user_count"], errors="coerce").fillna(0).astype(int).tolist(), label_opts=opts.LabelOpts(is_show=True))
        .add_yaxis("Avg Spend (k)", pd.to_numeric(disp["avg_spent_k"], errors="coerce").fillna(0.0).round(2).tolist(), label_opts=opts.LabelOpts(is_show=True))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="User Portrait: Member Level Comparison", subtitle="User count and average spending by member level"),
            xaxis_opts=opts.AxisOpts(name="Member Level", axislabel_opts=opts.LabelOpts(rotate=20)),
            yaxis_opts=opts.AxisOpts(name="Value"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _build_user_portrait_conclusion(age_df: pd.DataFrame, gender_df: pd.DataFrame, city_df: pd.DataFrame, member_df: pd.DataFrame) -> str:
    age_main = age_df.loc[age_df["user_count"].idxmax()] if not age_df.empty else None
    gender_main = gender_df.loc[gender_df["user_count"].idxmax()] if not gender_df.empty else None
    city_main = city_df.iloc[0] if not city_df.empty else None
    member_main = member_df.iloc[0] if not member_df.empty else None
    age_spend = age_df.loc[age_df["avg_spent"].idxmax()] if not age_df.empty else None
    member_spend = member_df.loc[member_df["avg_spent"].idxmax()] if not member_df.empty else None

    parts = []
    if age_main is not None:
        parts.append(f"largest age group: {age_main['age_group']} ({int(age_main['user_count'])} users)")
    if age_spend is not None:
        parts.append(f"highest average spending age group: {age_spend['age_group']}")
    if gender_main is not None:
        parts.append(f"gender majority: {gender_main['gender']}")
    if city_main is not None:
        parts.append(f"top city: {city_main['city']}")
    if member_main is not None:
        parts.append(f"largest member segment: {member_main['member_level']}")
    if member_spend is not None:
        parts.append(f"highest average spending member segment: {member_spend['member_level']}")
    return "User portrait shows " + "; ".join(parts) + "."


_base_get_dashboard_payload_with_portrait = get_dashboard_payload


def get_dashboard_payload() -> dict[str, Any]:
    payload = _base_get_dashboard_payload_with_portrait()
    prefer_hive = "Hive" in str(payload.get("data_source", ""))
    try:
        if prefer_hive:
            users, orders = _load_hive_users_orders()
        else:
            users, orders = _load_local_users_orders()
        _, age_df, gender_df, city_df, member_df = _build_user_portrait_frames(users, orders)
        payload["conclusions"]["User Portrait"] = _build_user_portrait_conclusion(age_df, gender_df, city_df, member_df)
        portrait_charts = [
            {"id": "chart_age_profile", "title": "User Portrait: Age Groups", "options": _chart_bar_age_profile(age_df)},
            {"id": "chart_gender_profile", "title": "User Portrait: Gender", "options": _chart_pie_gender_profile(gender_df)},
            {"id": "chart_city_profile", "title": "User Portrait: Top Cities", "options": _chart_bar_city_profile(city_df)},
            {"id": "chart_member_profile", "title": "User Portrait: Member Levels", "options": _chart_bar_member_profile(member_df)},
        ]
        payload["charts"] = payload["charts"] + portrait_charts
        payload["charts_mount"] = [{"id": c["id"], "title": c["title"], "options": json.loads(c["options"])} for c in payload["charts"]]
    except Exception as exc:
        logger.warning("User portrait analysis fallback/skip: %s", exc)
    return payload


def _load_kmeans_label_outputs() -> Optional[tuple[pd.DataFrame, pd.DataFrame]]:
    out_dir = PROJECT_ROOT / "docs" / "outputs"
    label_path = out_dir / "final_kmeans_cluster_labels.csv"
    summary_path = out_dir / "final_kmeans_cluster_summary.csv"
    if not label_path.exists() or not summary_path.exists():
        return None
    labels = pd.read_csv(label_path)
    cluster_summary = pd.read_csv(summary_path)
    labels["user_id"] = labels["user_id"].astype(str)
    return labels, cluster_summary


def _prepare_advanced_portrait_base(users: pd.DataFrame, orders: pd.DataFrame) -> Optional[pd.DataFrame]:
    bundle = _load_kmeans_label_outputs()
    if bundle is None:
        return None
    labels, cluster_summary = bundle
    cluster_name_map = {int(row["cluster"]): str(row["cluster_name"]) for _, row in cluster_summary.iterrows()}

    u = users.copy()
    o = orders.copy()
    u["user_id"] = u["user_id"].astype(str)
    u["age"] = pd.to_numeric(u["age"], errors="coerce")
    o["user_id"] = o["user_id"].astype(str)
    o["actual_payment"] = pd.to_numeric(o["actual_payment"], errors="coerce").fillna(0.0)
    spend = o.groupby("user_id", as_index=False).agg(total_spent=("actual_payment", "sum"))

    merged = u.merge(spend, on="user_id", how="left").merge(labels, on="user_id", how="left")
    merged["total_spent"] = pd.to_numeric(merged["total_spent"], errors="coerce").fillna(0.0)
    merged["cluster_name"] = merged["cluster"].map(cluster_name_map)
    merged["age_group"] = pd.cut(
        merged["age"],
        bins=[0, 25, 35, 45, 60, 120],
        labels=["<=25", "26-35", "36-45", "46-60", "60+"],
        include_lowest=True,
    )
    return merged


def _build_advanced_portrait_frames(base: pd.DataFrame) -> dict[str, pd.DataFrame]:
    high_value = base[base["rfm_label"] == "高价值用户"].copy()

    high_age = (
        high_value.groupby("age_group", observed=False)
        .agg(user_count=("user_id", "count"), avg_spent=("total_spent", "mean"))
        .reset_index()
        .dropna(subset=["age_group"])
    )
    high_gender = (
        high_value.groupby("gender", dropna=False)
        .agg(user_count=("user_id", "count"))
        .reset_index()
    )
    high_city = (
        high_value.groupby("city", dropna=False)
        .agg(user_count=("user_id", "count"))
        .reset_index()
        .sort_values("user_count", ascending=False)
        .head(10)
    )
    high_member = (
        high_value.groupby("member_level", dropna=False)
        .agg(user_count=("user_id", "count"), avg_spent=("total_spent", "mean"))
        .reset_index()
        .sort_values(["user_count", "avg_spent"], ascending=[False, False])
    )

    member_rfm = (
        base.groupby("member_level", dropna=False)
        .agg(
            total_users=("user_id", "count"),
            high_value_users=("rfm_label", lambda s: (s == "高价值用户").sum()),
        )
        .reset_index()
    )
    member_rfm["high_value_rate"] = member_rfm["high_value_users"] / member_rfm["total_users"].replace(0, 1)

    age_rfm = (
        base.groupby("age_group", observed=False)
        .agg(
            total_users=("user_id", "count"),
            churn_users=("rfm_label", lambda s: (s == "流失风险用户").sum()),
        )
        .reset_index()
        .dropna(subset=["age_group"])
    )
    age_rfm["churn_rate"] = age_rfm["churn_users"] / age_rfm["total_users"].replace(0, 1)

    cluster_gender = (
        base.groupby("cluster_name", dropna=False)
        .agg(
            total_users=("user_id", "count"),
            female_users=("gender", lambda s: (s == "女").sum()),
        )
        .reset_index()
        .dropna(subset=["cluster_name"])
    )
    cluster_gender["female_share"] = cluster_gender["female_users"] / cluster_gender["total_users"].replace(0, 1)

    top_cities = (
        base.groupby("city", dropna=False)
        .agg(user_count=("user_id", "count"))
        .reset_index()
        .sort_values("user_count", ascending=False)
        .head(8)["city"]
        .tolist()
    )
    city_cluster = (
        base[base["city"].isin(top_cities)]
        .groupby(["cluster_name", "city"], dropna=False)
        .size()
        .unstack(fill_value=0)
        .reset_index()
        .dropna(subset=["cluster_name"])
    )

    return {
        "high_age": high_age,
        "high_gender": high_gender,
        "high_city": high_city,
        "high_member": high_member,
        "member_rfm": member_rfm,
        "age_rfm": age_rfm,
        "cluster_gender": cluster_gender,
        "city_cluster": city_cluster,
    }


def _chart_high_value_age(df: pd.DataFrame) -> str:
    disp = df.copy()
    if disp.empty:
        disp = pd.DataFrame({"age_group": ["N/A"], "user_count": [0]})
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add_xaxis(disp["age_group"].astype(str).tolist())
        .add_yaxis("High Value Users", pd.to_numeric(disp["user_count"], errors="coerce").fillna(0).astype(int).tolist(), label_opts=opts.LabelOpts(is_show=True))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="High-Value User Portrait: Age Groups", subtitle="High-value users by age group"),
            xaxis_opts=opts.AxisOpts(name="Age Group"),
            yaxis_opts=opts.AxisOpts(name="User Count"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_high_value_gender(df: pd.DataFrame) -> str:
    disp = df.copy()
    if disp.empty:
        disp = pd.DataFrame({"gender": ["N/A"], "user_count": [1]})
    pie = (
        Pie(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add(
            series_name="High Value Gender",
            data_pair=[list(z) for z in zip(disp["gender"].astype(str).tolist(), pd.to_numeric(disp["user_count"], errors="coerce").fillna(0).tolist())],
            radius=["35%", "60%"],
            label_opts=opts.LabelOpts(formatter="{b}: {c} ({d}%)"),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(title="High-Value User Portrait: Gender", subtitle="Gender composition of high-value users"),
            tooltip_opts=opts.TooltipOpts(trigger="item"),
        )
    )
    return pie.dump_options_with_quotes()


def _chart_high_value_city(df: pd.DataFrame) -> str:
    disp = df.copy()
    if disp.empty:
        disp = pd.DataFrame({"city": ["N/A"], "user_count": [0]})
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="440px"))
        .add_xaxis(disp["city"].astype(str).tolist())
        .add_yaxis("High Value Users", pd.to_numeric(disp["user_count"], errors="coerce").fillna(0).astype(int).tolist(), label_opts=opts.LabelOpts(is_show=True))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="High-Value User Portrait: Top Cities", subtitle="Top cities with most high-value users"),
            xaxis_opts=opts.AxisOpts(name="City", axislabel_opts=opts.LabelOpts(rotate=25)),
            yaxis_opts=opts.AxisOpts(name="User Count"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_high_value_member(df: pd.DataFrame) -> str:
    disp = df.copy()
    if disp.empty:
        disp = pd.DataFrame({"member_level": ["N/A"], "user_count": [0]})
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add_xaxis(disp["member_level"].astype(str).tolist())
        .add_yaxis("High Value Users", pd.to_numeric(disp["user_count"], errors="coerce").fillna(0).astype(int).tolist(), label_opts=opts.LabelOpts(is_show=True))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="High-Value User Portrait: Member Levels", subtitle="Member-level distribution of high-value users"),
            xaxis_opts=opts.AxisOpts(name="Member Level", axislabel_opts=opts.LabelOpts(rotate=20)),
            yaxis_opts=opts.AxisOpts(name="User Count"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_member_high_value_rate(df: pd.DataFrame) -> str:
    disp = df.copy()
    disp["rate_pct"] = (pd.to_numeric(disp["high_value_rate"], errors="coerce").fillna(0.0) * 100).round(2)
    if disp.empty:
        disp = pd.DataFrame({"member_level": ["N/A"], "rate_pct": [0.0]})
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add_xaxis(disp["member_level"].astype(str).tolist())
        .add_yaxis("High Value Rate (%)", disp["rate_pct"].tolist(), label_opts=opts.LabelOpts(is_show=True, formatter="{c}"))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="Portrait × RFM: High-Value Rate by Member Level", subtitle="Share of high-value users in each member level"),
            xaxis_opts=opts.AxisOpts(name="Member Level", axislabel_opts=opts.LabelOpts(rotate=20)),
            yaxis_opts=opts.AxisOpts(name="Rate (%)"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_age_churn_rate(df: pd.DataFrame) -> str:
    disp = df.copy()
    disp["rate_pct"] = (pd.to_numeric(disp["churn_rate"], errors="coerce").fillna(0.0) * 100).round(2)
    if disp.empty:
        disp = pd.DataFrame({"age_group": ["N/A"], "rate_pct": [0.0]})
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add_xaxis(disp["age_group"].astype(str).tolist())
        .add_yaxis("Churn Risk Rate (%)", disp["rate_pct"].tolist(), label_opts=opts.LabelOpts(is_show=True, formatter="{c}"))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="Portrait × RFM: Churn Risk by Age Group", subtitle="Share of churn-risk users in each age group"),
            xaxis_opts=opts.AxisOpts(name="Age Group"),
            yaxis_opts=opts.AxisOpts(name="Rate (%)"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_cluster_female_share(df: pd.DataFrame) -> str:
    disp = df.copy()
    disp["share_pct"] = (pd.to_numeric(disp["female_share"], errors="coerce").fillna(0.0) * 100).round(2)
    if disp.empty:
        disp = pd.DataFrame({"cluster_name": ["N/A"], "share_pct": [0.0]})
    bar = (
        Bar(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="420px"))
        .add_xaxis(disp["cluster_name"].astype(str).tolist())
        .add_yaxis("Female Share (%)", disp["share_pct"].tolist(), label_opts=opts.LabelOpts(is_show=True, formatter="{c}"))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="Portrait × KMeans: Female Share by Cluster", subtitle="Gender composition across clusters"),
            xaxis_opts=opts.AxisOpts(name="Cluster", axislabel_opts=opts.LabelOpts(rotate=15)),
            yaxis_opts=opts.AxisOpts(name="Share (%)"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
    )
    return bar.dump_options_with_quotes()


def _chart_cluster_city_heatmap(df: pd.DataFrame) -> str:
    data = df.copy()
    if data.empty:
        data = pd.DataFrame({"cluster_name": ["N/A"], "N/A": [0]})
    clusters = data["cluster_name"].astype(str).tolist()
    city_cols = [c for c in data.columns if c != "cluster_name"]
    payload = []
    max_v = 1
    for yi, city in enumerate(city_cols):
        for xi, cluster in enumerate(clusters):
            v = int(pd.to_numeric(data.iloc[xi][city], errors="coerce") or 0)
            payload.append([xi, yi, v])
            max_v = max(max_v, v)
    hm = (
        HeatMap(init_opts=opts.InitOpts(theme=ThemeType.MACARONS, width="100%", height="480px"))
        .add_xaxis(clusters)
        .add_yaxis("Cities", city_cols, payload, label_opts=opts.LabelOpts(is_show=False))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="Portrait × KMeans: City Concentration by Cluster", subtitle="Top-city user concentration across clusters"),
            visualmap_opts=opts.VisualMapOpts(min_=0, max_=max_v, pos_top="middle"),
            tooltip_opts=opts.TooltipOpts(trigger="item"),
            xaxis_opts=opts.AxisOpts(name="Cluster"),
            yaxis_opts=opts.AxisOpts(name="City"),
        )
    )
    return hm.dump_options_with_quotes()


def _build_advanced_portrait_conclusion(frames: dict[str, pd.DataFrame]) -> str:
    high_age = frames["high_age"]
    high_member = frames["high_member"]
    member_rfm = frames["member_rfm"]
    age_rfm = frames["age_rfm"]
    cluster_gender = frames["cluster_gender"]
    city_cluster = frames["city_cluster"]

    parts = []
    if not high_age.empty:
        row = high_age.loc[high_age["user_count"].idxmax()]
        parts.append(f"high-value users are most concentrated in age group {row['age_group']}")
    if not high_member.empty:
        row = high_member.iloc[0]
        parts.append(f"the largest high-value member segment is {row['member_level']}")
    if not member_rfm.empty:
        row = member_rfm.loc[member_rfm["high_value_rate"].idxmax()]
        parts.append(f"{row['member_level']} has the highest high-value user rate")
    if not age_rfm.empty:
        row = age_rfm.loc[age_rfm["churn_rate"].idxmax()]
        parts.append(f"age group {row['age_group']} has the highest churn-risk rate")
    if not cluster_gender.empty:
        row = cluster_gender.loc[cluster_gender["female_share"].idxmax()]
        parts.append(f"{row['cluster_name']} has the highest female share")
    if not city_cluster.empty:
        city_cols = [c for c in city_cluster.columns if c != "cluster_name"]
        tmp = city_cluster.copy()
        tmp["top_city_count"] = tmp[city_cols].max(axis=1)
        row = tmp.loc[tmp["top_city_count"].idxmax()]
        top_city = row[city_cols].astype(float).idxmax()
        parts.append(f"{row['cluster_name']} is most concentrated in city {top_city}")
    return "Advanced user portrait analysis shows " + "; ".join(parts) + "."


_base_get_dashboard_payload_with_advanced_portrait = get_dashboard_payload


def get_dashboard_payload() -> dict[str, Any]:
    payload = _base_get_dashboard_payload_with_advanced_portrait()
    prefer_hive = "Hive" in str(payload.get("data_source", ""))
    try:
        if prefer_hive:
            users, orders = _load_hive_users_orders()
        else:
            users, orders = _load_local_users_orders()
        base = _prepare_advanced_portrait_base(users, orders)
        if base is None:
            return payload
        frames = _build_advanced_portrait_frames(base)
        payload["conclusions"]["Advanced Portrait"] = _build_advanced_portrait_conclusion(frames)
        advanced_charts = [
            {"id": "chart_high_value_age", "title": "Portrait: High-Value Age Groups", "options": _chart_high_value_age(frames["high_age"])},
            {"id": "chart_high_value_gender", "title": "Portrait: High-Value Gender", "options": _chart_high_value_gender(frames["high_gender"])},
            {"id": "chart_high_value_city", "title": "Portrait: High-Value Top Cities", "options": _chart_high_value_city(frames["high_city"])},
            {"id": "chart_high_value_member", "title": "Portrait: High-Value Member Levels", "options": _chart_high_value_member(frames["high_member"])},
            {"id": "chart_member_high_value_rate", "title": "Portrait × RFM: High-Value Rate", "options": _chart_member_high_value_rate(frames["member_rfm"])},
            {"id": "chart_age_churn_rate", "title": "Portrait × RFM: Churn Risk by Age", "options": _chart_age_churn_rate(frames["age_rfm"])},
            {"id": "chart_cluster_female_share", "title": "Portrait × KMeans: Female Share", "options": _chart_cluster_female_share(frames["cluster_gender"])},
            {"id": "chart_cluster_city_heatmap", "title": "Portrait × KMeans: City Concentration", "options": _chart_cluster_city_heatmap(frames["city_cluster"])},
        ]
        payload["charts"] = payload["charts"] + advanced_charts
        payload["charts_mount"] = [{"id": c["id"], "title": c["title"], "options": json.loads(c["options"])} for c in payload["charts"]]
    except Exception as exc:
        logger.warning("Advanced portrait analysis fallback/skip: %s", exc)
    return payload
