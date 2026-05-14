from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "docs" / "data"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


BEHAVIOR_MAP = {"浏览": "browse", "点击": "click", "收藏": "favorite", "加购": "cart", "购买": "buy"}
MEMBER_LEVEL_MAP = {"普通会员": 1, "铜牌会员": 2, "银牌会员": 3, "金牌会员": 4, "钻石会员": 5}
COMPLETED_STATUSES = {"已完成", "已收货"}
REFUND_STATUSES = {"已退款"}
CANCELLED_STATUSES = {"已取消"}


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace(0, np.nan)
    out = numerator / denominator
    return out.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def build_features_pandas() -> pd.DataFrame:
    users = pd.read_csv(DATA_DIR / "users.csv")
    orders = pd.read_csv(DATA_DIR / "orders.csv")
    behaviors = pd.read_csv(DATA_DIR / "user_behaviors.csv")

    orders["order_date"] = pd.to_datetime(orders["order_date"], errors="coerce")
    orders["actual_payment"] = pd.to_numeric(orders["actual_payment"], errors="coerce").fillna(0.0)
    orders["quantity"] = pd.to_numeric(orders["quantity"], errors="coerce").fillna(0.0)
    orders["review_score"] = pd.to_numeric(orders["review_score"], errors="coerce")

    users["account_balance"] = pd.to_numeric(users["account_balance"], errors="coerce").fillna(0.0)
    users["credit_score"] = pd.to_numeric(users["credit_score"], errors="coerce").fillna(users["credit_score"].median())
    users["age"] = pd.to_numeric(users["age"], errors="coerce").fillna(users["age"].median())
    users["registration_date"] = pd.to_datetime(users["registration_date"], errors="coerce")

    behaviors["behavior_key"] = behaviors["behavior_type"].map(BEHAVIOR_MAP)
    behaviors["duration_seconds"] = pd.to_numeric(behaviors["duration_seconds"], errors="coerce").fillna(0.0)

    order_features = (
        orders.groupby("user_id")
        .agg(
            total_spent=("actual_payment", "sum"),
            order_count=("order_id", "count"),
            avg_order_amount=("actual_payment", "mean"),
            total_quantity=("quantity", "sum"),
            last_order_date=("order_date", "max"),
            avg_review_score=("review_score", "mean"),
            reviewed_orders=("review_score", lambda s: s.notna().sum()),
            completed_orders=("order_status", lambda s: s.isin(COMPLETED_STATUSES).sum()),
            refunded_orders=("order_status", lambda s: s.isin(REFUND_STATUSES).sum()),
            cancelled_orders=("order_status", lambda s: s.isin(CANCELLED_STATUSES).sum()),
        )
        .reset_index()
    )

    behavior_features = (
        behaviors.pivot_table(
            index="user_id",
            columns="behavior_key",
            values="behavior_id",
            aggfunc="count",
            fill_value=0,
        )
        .reset_index()
    )
    for col in ["browse", "click", "favorite", "cart", "buy"]:
        if col not in behavior_features.columns:
            behavior_features[col] = 0

    duration_features = (
        behaviors.groupby("user_id")
        .agg(avg_duration_seconds=("duration_seconds", "mean"))
        .reset_index()
    )

    df = users.merge(order_features, on="user_id", how="left")
    df = df.merge(behavior_features, on="user_id", how="left")
    df = df.merge(duration_features, on="user_id", how="left")

    numeric_defaults = {
        "total_spent": 0.0,
        "order_count": 0.0,
        "avg_order_amount": 0.0,
        "total_quantity": 0.0,
        "avg_review_score": 3.0,
        "reviewed_orders": 0.0,
        "completed_orders": 0.0,
        "refunded_orders": 0.0,
        "cancelled_orders": 0.0,
        "browse": 0.0,
        "click": 0.0,
        "favorite": 0.0,
        "cart": 0.0,
        "buy": 0.0,
        "avg_duration_seconds": 0.0,
    }
    for col, default in numeric_defaults.items():
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(default)

    ref_date = orders["order_date"].max()
    df["last_order_date"] = pd.to_datetime(df["last_order_date"], errors="coerce")
    df["recency_days"] = (ref_date - df["last_order_date"]).dt.days
    max_recency = df["recency_days"].dropna().max()
    df["recency_days"] = df["recency_days"].fillna(max_recency if pd.notna(max_recency) else 999)

    df["member_level_score"] = df["member_level"].map(MEMBER_LEVEL_MAP).fillna(1)
    df["registration_days"] = (ref_date - df["registration_date"]).dt.days
    max_reg = df["registration_days"].dropna().max()
    df["registration_days"] = df["registration_days"].fillna(max_reg if pd.notna(max_reg) else 365)

    # Newly added ratio features
    df["completion_rate"] = safe_ratio(df["completed_orders"], df["order_count"])
    df["refund_rate"] = safe_ratio(df["refunded_orders"], df["order_count"])
    df["cancel_rate"] = safe_ratio(df["cancelled_orders"], df["order_count"])
    df["review_rate"] = safe_ratio(df["reviewed_orders"], df["order_count"])
    df["click_through_rate"] = safe_ratio(df["click"], df["browse"])
    df["favorite_rate"] = safe_ratio(df["favorite"], df["browse"])
    df["cart_rate"] = safe_ratio(df["cart"], df["browse"])
    df["cart_to_favorite_ratio"] = safe_ratio(df["cart"], df["favorite"].replace(0, 1))

    # Keep a smaller but stronger feature set: remove weak/constant signals like buy in current behavior table.
    df["engagement_score"] = (
        df["browse"] * 0.10
        + df["click"] * 0.35
        + df["favorite"] * 0.75
        + df["cart"] * 1.00
    )

    # Reduce skew in monetary features.
    df["log_total_spent"] = np.log1p(df["total_spent"].clip(lower=0))
    df["log_avg_order_amount"] = np.log1p(df["avg_order_amount"].clip(lower=0))
    df["log_account_balance"] = np.log1p(df["account_balance"].clip(lower=0))
    df["log_total_quantity"] = np.log1p(df["total_quantity"].clip(lower=0))

    # Clean impossible values
    df["avg_review_score"] = df["avg_review_score"].clip(lower=0, upper=5)
    df["credit_score"] = df["credit_score"].clip(lower=0)
    df["age"] = df["age"].clip(lower=0)

    return df


def build_rfm_labels(df: pd.DataFrame) -> pd.DataFrame:
    base = df[["user_id", "recency_days", "order_count", "total_spent"]].copy()

    def q5(series: pd.Series, labels: list[int]) -> pd.Series:
        try:
            return pd.qcut(series, q=5, labels=labels, duplicates="drop").astype(float)
        except ValueError:
            return pd.Series([3.0] * len(series), index=series.index)

    base["r_score"] = q5(base["recency_days"], [5, 4, 3, 2, 1])
    base["f_score"] = q5(base["order_count"], [1, 2, 3, 4, 5])
    base["m_score"] = q5(base["total_spent"], [1, 2, 3, 4, 5])

    def label(row: pd.Series) -> str:
        r, f, m = int(row["r_score"]), int(row["f_score"]), int(row["m_score"])
        if r >= 4 and f >= 4 and m >= 4:
            return "高价值用户"
        if r >= 3 and f >= 3:
            return "潜力用户"
        if r <= 2 and f <= 2:
            return "流失风险用户"
        return "一般用户"

    base["rfm_label"] = base.apply(label, axis=1)
    return base


def _label_cluster(summary_df: pd.DataFrame) -> pd.DataFrame:
    out = summary_df.copy()
    revenue_col = "avg(log_total_spent)"
    if revenue_col not in out.columns:
        for candidate in ["avg(total_spent)", "avg(log_avg_order_amount)", "avg(avg_order_amount)"]:
            if candidate in out.columns:
                revenue_col = candidate
                break
    recency_col = "avg(recency_days)"
    completion_col = "avg(completion_rate)"
    engagement_col = "avg(engagement_score)"
    if completion_col not in out.columns:
        for candidate in ["avg(avg_review_score)", "avg(refund_rate)"]:
            if candidate in out.columns:
                completion_col = candidate
                break
    if engagement_col not in out.columns:
        for candidate in ["avg(click_through_rate)", "avg(favorite_rate)", "avg(cart_rate)"]:
            if candidate in out.columns:
                engagement_col = candidate
                break
    out["cluster_name"] = "一般活跃群体"

    high_cluster = out[revenue_col].idxmax()
    out.loc[high_cluster, "cluster_name"] = "高价值核心群体"

    churn_cluster = out[recency_col].idxmax()
    out.loc[churn_cluster, "cluster_name"] = "流失风险群体"

    remaining = out[out["cluster_name"] == "一般活跃群体"].copy()
    if not remaining.empty:
        growth_cluster = remaining[engagement_col].idxmax()
        out.loc[growth_cluster, "cluster_name"] = "潜力成长群体"

    remaining = out[out["cluster_name"] == "一般活跃群体"].copy()
    if not remaining.empty:
        stable_cluster = remaining[completion_col].idxmax()
        out.loc[stable_cluster, "cluster_name"] = "中等价值稳定群体"
    return out


FEATURE_PROFILES = {
    "baseline": [
        "recency_days",
        "order_count",
        "total_spent",
        "avg_order_amount",
        "total_quantity",
        "browse",
        "click",
        "favorite",
        "cart",
        "avg_duration_seconds",
        "member_level_score",
        "click_through_rate",
        "favorite_rate",
        "cart_rate",
        "log_account_balance",
    ],
    "quality_enhanced": [
        "recency_days",
        "order_count",
        "log_total_spent",
        "log_avg_order_amount",
        "total_quantity",
        "browse",
        "click",
        "favorite",
        "cart",
        "avg_duration_seconds",
        "member_level_score",
        "click_through_rate",
        "favorite_rate",
        "cart_rate",
        "completion_rate",
        "refund_rate",
        "avg_review_score",
        "credit_score",
        "log_account_balance",
    ],
    "compact_ratio": [
        "recency_days",
        "order_count",
        "log_total_spent",
        "completion_rate",
        "refund_rate",
        "avg_review_score",
        "click_through_rate",
        "favorite_rate",
        "cart_rate",
        "engagement_score",
        "member_level_score",
        "credit_score",
        "log_account_balance",
    ],
    "compact_no_engagement": [
        "recency_days",
        "order_count",
        "log_total_spent",
        "completion_rate",
        "refund_rate",
        "avg_review_score",
        "click_through_rate",
        "favorite_rate",
        "cart_rate",
        "member_level_score",
        "credit_score",
        "log_account_balance",
    ],
    "compact_no_member": [
        "recency_days",
        "order_count",
        "log_total_spent",
        "completion_rate",
        "refund_rate",
        "avg_review_score",
        "click_through_rate",
        "favorite_rate",
        "cart_rate",
        "engagement_score",
        "credit_score",
        "log_account_balance",
    ],
    "compact_no_engagement_no_member": [
        "recency_days",
        "order_count",
        "log_total_spent",
        "completion_rate",
        "refund_rate",
        "avg_review_score",
        "click_through_rate",
        "favorite_rate",
        "cart_rate",
        "credit_score",
        "log_account_balance",
    ],
    "compact_plus_cancel": [
        "recency_days",
        "order_count",
        "log_total_spent",
        "completion_rate",
        "refund_rate",
        "cancel_rate",
        "avg_review_score",
        "click_through_rate",
        "favorite_rate",
        "cart_rate",
        "credit_score",
        "log_account_balance",
    ],
    "compact_plus_review_rate": [
        "recency_days",
        "order_count",
        "log_total_spent",
        "completion_rate",
        "refund_rate",
        "review_rate",
        "avg_review_score",
        "click_through_rate",
        "favorite_rate",
        "cart_rate",
        "credit_score",
        "log_account_balance",
    ],
    "compact_plus_registration": [
        "recency_days",
        "order_count",
        "log_total_spent",
        "completion_rate",
        "refund_rate",
        "avg_review_score",
        "click_through_rate",
        "favorite_rate",
        "cart_rate",
        "credit_score",
        "log_account_balance",
        "registration_days",
    ],
    "compact_plus_all_quality": [
        "recency_days",
        "order_count",
        "log_total_spent",
        "completion_rate",
        "refund_rate",
        "cancel_rate",
        "review_rate",
        "avg_review_score",
        "click_through_rate",
        "favorite_rate",
        "cart_rate",
        "credit_score",
        "log_account_balance",
        "registration_days",
    ],
    "quality_no_browse": [
        "recency_days",
        "order_count",
        "log_total_spent",
        "log_avg_order_amount",
        "total_quantity",
        "click",
        "favorite",
        "cart",
        "avg_duration_seconds",
        "member_level_score",
        "click_through_rate",
        "favorite_rate",
        "cart_rate",
        "completion_rate",
        "refund_rate",
        "avg_review_score",
        "credit_score",
        "log_account_balance",
    ],
}


def get_feature_columns(profile: str = "compact_no_engagement_no_member") -> list[str]:
    if profile not in FEATURE_PROFILES:
        raise ValueError(f"Unknown feature profile: {profile}")
    return FEATURE_PROFILES[profile]


def run_with_pyspark(k: int, output_prefix: str, feature_profile: str = "compact_no_engagement_no_member") -> dict:
    current_python = os.environ.get("PYSPARK_PYTHON") or os.environ.get("PYSPARK_DRIVER_PYTHON")
    if not current_python:
        current_python = os.sys.executable
        os.environ["PYSPARK_PYTHON"] = current_python
        os.environ["PYSPARK_DRIVER_PYTHON"] = current_python

    from pyspark.ml.clustering import KMeans
    from pyspark.ml.evaluation import ClusteringEvaluator
    from pyspark.ml.feature import StandardScaler, VectorAssembler
    from pyspark.sql import SparkSession

    pdf = build_features_pandas()
    rfm = build_rfm_labels(pdf)
    merged = pdf.merge(rfm[["user_id", "rfm_label"]], on="user_id", how="left")

    spark = SparkSession.builder.appName("taobao-kmeans-rfm").master("local[*]").getOrCreate()
    sdf = spark.createDataFrame(merged)

    feature_cols = get_feature_columns(feature_profile)
    assembler = VectorAssembler(inputCols=feature_cols, outputCol="features_raw")
    assembled = assembler.transform(sdf)
    scaler = StandardScaler(inputCol="features_raw", outputCol="features", withStd=True, withMean=True)
    scaled = scaler.fit(assembled).transform(assembled)

    model = KMeans(featuresCol="features", predictionCol="cluster", k=k, seed=42, maxIter=40).fit(scaled)
    predicted = model.transform(scaled)

    evaluator = ClusteringEvaluator(featuresCol="features", predictionCol="cluster", metricName="silhouette")
    silhouette = evaluator.evaluate(predicted)

    result_pdf = predicted.select("user_id", "cluster", "rfm_label").toPandas()
    cluster_summary = predicted.groupBy("cluster").avg(*feature_cols).toPandas().sort_values("cluster")
    cluster_summary = _label_cluster(cluster_summary)
    cross_tab = pd.crosstab(result_pdf["cluster"], result_pdf["rfm_label"])

    result_pdf.to_csv(OUTPUT_DIR / f"{output_prefix}_cluster_labels.csv", index=False, encoding="utf-8-sig")
    cluster_summary.to_csv(OUTPUT_DIR / f"{output_prefix}_cluster_summary.csv", index=False, encoding="utf-8-sig")
    cross_tab.to_csv(OUTPUT_DIR / f"{output_prefix}_rfm_vs_kmeans.csv", encoding="utf-8-sig")

    summary = {
        "mode": "pyspark",
        "k": k,
        "feature_profile": feature_profile,
        "silhouette_score": float(silhouette),
        "feature_columns": feature_cols,
        "output_files": [
            f"{output_prefix}_cluster_labels.csv",
            f"{output_prefix}_cluster_summary.csv",
            f"{output_prefix}_rfm_vs_kmeans.csv",
        ],
    }
    spark.stop()
    return summary


def compare_k_values(k_values: Iterable[int], output_prefix: str, feature_profile: str = "compact_no_engagement_no_member") -> dict:
    rows: list[dict[str, float | int]] = []
    for k in k_values:
        summary = run_with_pyspark(k, f"{output_prefix}_k{k}", feature_profile=feature_profile)
        rows.append({"k": k, "silhouette_score": summary["silhouette_score"]})
    out = pd.DataFrame(rows).sort_values("silhouette_score", ascending=False)
    out.to_csv(OUTPUT_DIR / f"{output_prefix}_k_comparison.csv", index=False, encoding="utf-8-sig")
    return {
        "mode": "pyspark",
        "feature_profile": feature_profile,
        "k_values": list(k_values),
        "best_k": int(out.iloc[0]["k"]),
        "best_silhouette_score": float(out.iloc[0]["silhouette_score"]),
        "output_files": [f"{output_prefix}_k_comparison.csv"],
    }


def compare_feature_profiles(profiles: Iterable[str], k: int, output_prefix: str) -> dict:
    rows: list[dict[str, float | int | str]] = []
    for profile in profiles:
        summary = run_with_pyspark(k, f"{output_prefix}_{profile}", feature_profile=profile)
        rows.append(
            {
                "feature_profile": profile,
                "k": k,
                "silhouette_score": summary["silhouette_score"],
                "feature_count": len(summary["feature_columns"]),
            }
        )
    out = pd.DataFrame(rows).sort_values("silhouette_score", ascending=False)
    out.to_csv(OUTPUT_DIR / f"{output_prefix}_profile_comparison.csv", index=False, encoding="utf-8-sig")
    return {
        "mode": "pyspark",
        "comparison_type": "feature_profile",
        "k": k,
        "best_profile": str(out.iloc[0]["feature_profile"]),
        "best_silhouette_score": float(out.iloc[0]["silhouette_score"]),
        "output_files": [f"{output_prefix}_profile_comparison.csv"],
    }


def run_fallback(output_prefix: str) -> dict:
    pdf = build_features_pandas()
    rfm = build_rfm_labels(pdf)
    merged = pdf.merge(rfm[["user_id", "rfm_label"]], on="user_id", how="left")
    merged.to_csv(OUTPUT_DIR / f"{output_prefix}_feature_table.csv", index=False, encoding="utf-8-sig")
    rfm.to_csv(OUTPUT_DIR / f"{output_prefix}_rfm_labels.csv", index=False, encoding="utf-8-sig")
    return {
        "mode": "fallback",
        "message": "pyspark not installed; exported feature table and RFM labels only",
        "output_files": [f"{output_prefix}_feature_table.csv", f"{output_prefix}_rfm_labels.csv"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Spark KMeans and RFM comparison.")
    parser.add_argument("--k", type=int, default=4, help="Number of KMeans clusters")
    parser.add_argument("--output-prefix", default="spark_kmeans_rfm")
    parser.add_argument("--compare-k", nargs="*", type=int, default=None, help="Optional list of k values to compare")
    parser.add_argument(
        "--compare-profiles",
        nargs="*",
        default=None,
        help="Optional list of feature profiles to compare under the same k",
    )
    parser.add_argument(
        "--feature-profile",
        default="compact_no_engagement_no_member",
        choices=sorted(FEATURE_PROFILES.keys()),
        help="Preset feature profile to evaluate",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.compare_profiles:
            summary = compare_feature_profiles(args.compare_profiles, args.k, args.output_prefix)
        elif args.compare_k:
            summary = compare_k_values(args.compare_k, args.output_prefix, feature_profile=args.feature_profile)
        else:
            summary = run_with_pyspark(args.k, args.output_prefix, feature_profile=args.feature_profile)
    except ModuleNotFoundError as exc:
        if exc.name == "pyspark":
            summary = run_fallback(args.output_prefix)
        else:
            raise

    summary_path = OUTPUT_DIR / f"{args.output_prefix}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
