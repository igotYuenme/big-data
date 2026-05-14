from __future__ import annotations

import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "docs" / "figures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR = PROJECT_ROOT / "docs" / "data"
MYSQL_OUTPUT_DIR = PROJECT_ROOT / "docs" / "outputs" / "mysql_acceptance"
KMEANS_OUTPUT_DIR = PROJECT_ROOT / "docs" / "outputs"

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.unicode_minus"] = False
sns.set_theme(style="whitegrid")

MEMBER_LEVEL_EN = {
    "普通会员": "Regular",
    "铜牌会员": "Bronze",
    "银牌会员": "Silver",
    "金牌会员": "Gold",
    "钻石会员": "Diamond",
}
CLUSTER_NAME_EN = {
    "高价值核心群体": "High Value Core",
    "流失风险群体": "Churn Risk",
    "潜力成长群体": "Growth Potential",
    "中等价值稳定群体": "Stable Mid-Value",
    "一般活跃群体": "Active General",
}
RFM_LABEL_EN = {
    "一般用户": "General",
    "流失风险用户": "Churn Risk",
    "潜力用户": "Potential",
    "高价值用户": "High Value",
}
GENDER_EN = {"男": "Male", "女": "Female"}


def _save(fig: plt.Figure, filename: str) -> Path:
    fig.tight_layout()
    path = OUTPUT_DIR / filename
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return path


def _mysql_engine():
    host = os.environ.get("MYSQL_HOST", "127.0.0.1")
    port = os.environ.get("MYSQL_PORT", "3306")
    user = os.environ.get("MYSQL_USER", "root")
    password = os.environ.get("MYSQL_PASSWORD", "")
    database = os.environ.get("MYSQL_DATABASE", "taobao_analysis")
    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"
    return create_engine(url, future=True)


def export_mysql_table_counts() -> list[Path]:
    engine = _mysql_engine()
    rows = []
    with engine.connect() as conn:
        for table in ["users", "products", "orders", "user_behaviors"]:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            rows.append({"table_name": table, "row_count": int(count or 0)})
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_DIR / "mysql_table_counts.csv", index=False, encoding="utf-8-sig")

    fig, ax = plt.subplots(figsize=(8, 5))
    sns.barplot(data=df, x="table_name", y="row_count", hue="table_name", dodge=False, palette="Blues_d", legend=False, ax=ax)
    ax.set_title("MySQL Import Validation: Row Counts by Table")
    ax.set_xlabel("Table Name")
    ax.set_ylabel("Row Count")
    for idx, row in df.iterrows():
        ax.text(idx, row["row_count"], f"{row['row_count']}", ha="center", va="bottom", fontsize=10)
    return [_save(fig, "mysql_table_counts.png")]


def export_mysql_query_figures() -> list[Path]:
    outputs: list[Path] = []

    q2 = pd.read_csv(MYSQL_OUTPUT_DIR / "query_2.csv").head(10)
    q2["member_level_en"] = q2["member_level"].map(MEMBER_LEVEL_EN).fillna("Other")
    fig, ax = plt.subplots(figsize=(10, 5.5))
    sns.barplot(data=q2, x="user_id", y="total_spent", hue="member_level_en", dodge=False, palette="viridis", ax=ax)
    ax.set_title("MySQL Query Result: Top 10 Users by Total Spending")
    ax.set_xlabel("User ID")
    ax.set_ylabel("Total Spending")
    ax.tick_params(axis="x", rotation=30)
    ax.legend(title="Member Level")
    outputs.append(_save(fig, "mysql_top_users_total_spent.png"))

    q3 = pd.read_csv(MYSQL_OUTPUT_DIR / "query_3.csv").head(10)
    category_map = {name: f"Category {idx + 1}" for idx, name in enumerate(q3["category"].dropna().unique())}
    q3["category_en"] = q3["category"].map(category_map).fillna("Category")
    fig, ax = plt.subplots(figsize=(10, 5.5))
    sns.barplot(data=q3, x="product_id", y="total_revenue", hue="category_en", dodge=False, palette="magma", ax=ax)
    ax.set_title("MySQL Query Result: Top 10 Products by Revenue")
    ax.set_xlabel("Product ID")
    ax.set_ylabel("Total Revenue")
    ax.tick_params(axis="x", rotation=30)
    ax.legend(title="Category", bbox_to_anchor=(1.02, 1), loc="upper left")
    outputs.append(_save(fig, "mysql_top_products_revenue.png"))

    q4 = pd.read_csv(MYSQL_OUTPUT_DIR / "query_4.csv").head(10)
    q4["city_rank"] = [f"City {idx + 1}" for idx in range(len(q4))]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    sns.barplot(data=q4, x="city_rank", y="total_revenue", hue="city_rank", dodge=False, palette="crest", legend=False, ax=ax)
    ax.set_title("MySQL Query Result: Top 10 Cities by Revenue")
    ax.set_xlabel("City Rank")
    ax.set_ylabel("Total Revenue")
    ax.tick_params(axis="x", rotation=30)
    outputs.append(_save(fig, "mysql_city_total_revenue.png"))

    q5 = pd.read_csv(MYSQL_OUTPUT_DIR / "query_5.csv").head(12)
    q5["behavior_total"] = q5[["browse_count", "click_count", "favorite_count", "cart_count"]].sum(axis=1)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    sns.scatterplot(
        data=q5,
        x="behavior_total",
        y="total_spent",
        size="purchase_count",
        hue="purchase_count",
        palette="rocket",
        sizes=(80, 280),
        ax=ax,
    )
    for _, row in q5.iterrows():
        ax.text(row["behavior_total"], row["total_spent"], row["user_id"], fontsize=8)
    ax.set_title("MySQL Query Result: Behavior Volume vs Total Spending")
    ax.set_xlabel("Behavior Volume")
    ax.set_ylabel("Total Spending")
    outputs.append(_save(fig, "mysql_behavior_vs_spent.png"))
    return outputs


def export_kmeans_figures() -> list[Path]:
    outputs: list[Path] = []
    compare = pd.read_csv(KMEANS_OUTPUT_DIR / "kmeans_compare_k_comparison.csv")
    fig, ax = plt.subplots(figsize=(8, 5))
    sns.barplot(data=compare, x="k", y="silhouette_score", hue="k", dodge=False, palette="flare", legend=False, ax=ax)
    ax.set_title("Spark KMeans: Silhouette Score by K")
    ax.set_xlabel("K Value")
    ax.set_ylabel("Silhouette Score")
    for idx, row in compare.iterrows():
        ax.text(idx, row["silhouette_score"], f"{row['silhouette_score']:.4f}", ha="center", va="bottom", fontsize=10)
    outputs.append(_save(fig, "kmeans_silhouette_comparison.png"))

    ablation_path = KMEANS_OUTPUT_DIR / "ablation_profile_comparison.csv"
    if ablation_path.exists():
        ablation = pd.read_csv(ablation_path)
        fig, ax = plt.subplots(figsize=(10, 5.5))
        sns.barplot(data=ablation, x="feature_profile", y="silhouette_score", hue="feature_profile", dodge=False, palette="husl", legend=False, ax=ax)
        ax.set_title("Feature Ablation Comparison")
        ax.set_xlabel("Feature Profile")
        ax.set_ylabel("Silhouette Score")
        ax.tick_params(axis="x", rotation=18)
        for idx, row in ablation.iterrows():
            ax.text(idx, row["silhouette_score"], f"{row['silhouette_score']:.4f}", ha="center", va="bottom", fontsize=9)
        outputs.append(_save(fig, "kmeans_feature_ablation.png"))

    cluster_summary = pd.read_csv(KMEANS_OUTPUT_DIR / "kmeans_compare_k3_cluster_summary.csv")
    cluster_summary["cluster_name_en"] = cluster_summary["cluster_name"].map(CLUSTER_NAME_EN).fillna(cluster_summary["cluster_name"])
    spend_col = "avg(total_spent)" if "avg(total_spent)" in cluster_summary.columns else "avg(log_total_spent)"
    fig, ax = plt.subplots(figsize=(10, 5.5))
    sns.barplot(data=cluster_summary, x="cluster_name_en", y=spend_col, hue="cluster_name_en", dodge=False, palette="Set2", legend=False, ax=ax)
    ax.set_title("KMeans Cluster Profile: Average Spending")
    ax.set_xlabel("Cluster")
    ax.set_ylabel("Average Spending")
    ax.tick_params(axis="x", rotation=15)
    outputs.append(_save(fig, "kmeans_cluster_value_profile.png"))

    cross = pd.read_csv(KMEANS_OUTPUT_DIR / "kmeans_compare_k3_rfm_vs_kmeans.csv")
    cross = cross.rename(columns={col: RFM_LABEL_EN.get(col, col) for col in cross.columns})
    heatmap_df = cross.set_index("cluster")
    fig, ax = plt.subplots(figsize=(8, 5.5))
    sns.heatmap(heatmap_df, annot=True, fmt="d", cmap="YlOrRd", ax=ax)
    ax.set_title("RFM vs KMeans Cross-Tab Heatmap")
    ax.set_xlabel("RFM Label")
    ax.set_ylabel("KMeans Cluster")
    outputs.append(_save(fig, "rfm_kmeans_heatmap.png"))

    fig, ax = plt.subplots(figsize=(10, 5.5))
    metric_df = cluster_summary[["cluster_name_en", "avg(order_count)", spend_col, "avg(click_through_rate)"]].copy()
    metric_df = metric_df.rename(
        columns={
            "cluster_name_en": "cluster_name",
            "avg(order_count)": "Average Order Count",
            spend_col: "Average Spending",
            "avg(click_through_rate)": "Average CTR",
        }
    )
    melted = metric_df.melt(id_vars="cluster_name", var_name="metric", value_name="value")
    sns.barplot(data=melted, x="cluster_name", y="value", hue="metric", ax=ax)
    ax.set_title("KMeans Cluster Comparison: Core Metrics")
    ax.set_xlabel("Cluster")
    ax.set_ylabel("Metric Value")
    ax.tick_params(axis="x", rotation=15)
    outputs.append(_save(fig, "kmeans_cluster_metric_compare.png"))
    return outputs


def _load_advanced_portrait_frames() -> dict[str, pd.DataFrame] | None:
    users_path = DATA_DIR / "users.csv"
    orders_path = DATA_DIR / "orders.csv"
    labels_path = KMEANS_OUTPUT_DIR / "final_kmeans_cluster_labels.csv"
    cluster_summary_path = KMEANS_OUTPUT_DIR / "final_kmeans_cluster_summary.csv"
    if not (users_path.exists() and orders_path.exists() and labels_path.exists() and cluster_summary_path.exists()):
        return None

    users = pd.read_csv(users_path)
    orders = pd.read_csv(orders_path)
    labels = pd.read_csv(labels_path)
    cluster_summary = pd.read_csv(cluster_summary_path)

    users["user_id"] = users["user_id"].astype(str)
    users["age"] = pd.to_numeric(users["age"], errors="coerce")
    users["gender_en"] = users["gender"].map(GENDER_EN).fillna("Unknown")
    users["member_level_en"] = users["member_level"].map(MEMBER_LEVEL_EN).fillna("Other")

    orders["user_id"] = orders["user_id"].astype(str)
    orders["actual_payment"] = pd.to_numeric(orders["actual_payment"], errors="coerce").fillna(0.0)
    spend = orders.groupby("user_id", as_index=False).agg(total_spent=("actual_payment", "sum"))

    labels["user_id"] = labels["user_id"].astype(str)
    cluster_name_map = {
        int(row["cluster"]): CLUSTER_NAME_EN.get(str(row["cluster_name"]), str(row["cluster_name"]))
        for _, row in cluster_summary.iterrows()
    }
    labels["cluster_name_en"] = labels["cluster"].map(cluster_name_map)

    merged = users.merge(spend, on="user_id", how="left").merge(labels, on="user_id", how="left")
    merged["total_spent"] = pd.to_numeric(merged["total_spent"], errors="coerce").fillna(0.0)
    merged["age_group"] = pd.cut(
        merged["age"],
        bins=[0, 25, 35, 45, 60, 120],
        labels=["<=25", "26-35", "36-45", "46-60", "60+"],
        include_lowest=True,
    )

    high_value = merged[merged["rfm_label"] == "高价值用户"].copy()
    high_age = high_value.groupby("age_group", observed=False).agg(user_count=("user_id", "count")).reset_index().dropna(subset=["age_group"])
    high_gender = high_value.groupby("gender_en", dropna=False).agg(user_count=("user_id", "count")).reset_index()
    high_city = high_value.groupby("city", dropna=False).agg(user_count=("user_id", "count")).reset_index().sort_values("user_count", ascending=False).head(10)
    high_city["city_rank"] = [f"City {i + 1}" for i in range(len(high_city))]
    high_member = high_value.groupby("member_level_en", dropna=False).agg(user_count=("user_id", "count")).reset_index().sort_values("user_count", ascending=False)

    member_rfm = merged.groupby("member_level_en", dropna=False).agg(
        total_users=("user_id", "count"),
        high_value_users=("rfm_label", lambda s: (s == "高价值用户").sum()),
    ).reset_index()
    member_rfm["high_value_rate"] = member_rfm["high_value_users"] / member_rfm["total_users"].replace(0, 1)

    age_rfm = merged.groupby("age_group", observed=False).agg(
        total_users=("user_id", "count"),
        churn_users=("rfm_label", lambda s: (s == "流失风险用户").sum()),
    ).reset_index().dropna(subset=["age_group"])
    age_rfm["churn_rate"] = age_rfm["churn_users"] / age_rfm["total_users"].replace(0, 1)

    cluster_gender = merged.groupby("cluster_name_en", dropna=False).agg(
        total_users=("user_id", "count"),
        female_users=("gender_en", lambda s: (s == "Female").sum()),
    ).reset_index().dropna(subset=["cluster_name_en"])
    cluster_gender["female_share"] = cluster_gender["female_users"] / cluster_gender["total_users"].replace(0, 1)

    top_cities = merged.groupby("city", dropna=False).agg(user_count=("user_id", "count")).reset_index().sort_values("user_count", ascending=False).head(8)["city"].tolist()
    city_label_map = {city: f"City {idx + 1}" for idx, city in enumerate(top_cities)}
    city_cluster = (
        merged[merged["city"].isin(top_cities)]
        .groupby(["cluster_name_en", "city"], dropna=False)
        .size()
        .unstack(fill_value=0)
        .reset_index()
        .dropna(subset=["cluster_name_en"])
        .rename(columns=city_label_map)
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


def export_advanced_portrait_figures() -> list[Path]:
    frames = _load_advanced_portrait_frames()
    if frames is None:
        return []
    outputs: list[Path] = []

    fig, ax = plt.subplots(figsize=(8.5, 5))
    sns.barplot(data=frames["high_age"], x="age_group", y="user_count", hue="age_group", dodge=False, palette="Blues", legend=False, ax=ax)
    ax.set_title("High-Value User Portrait: Age Groups")
    ax.set_xlabel("Age Group")
    ax.set_ylabel("High-Value User Count")
    outputs.append(_save(fig, "portrait_high_value_age.png"))

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(frames["high_gender"]["user_count"], labels=frames["high_gender"]["gender_en"], autopct="%1.1f%%", startangle=90)
    ax.set_title("High-Value User Portrait: Gender Distribution")
    outputs.append(_save(fig, "portrait_high_value_gender.png"))

    fig, ax = plt.subplots(figsize=(8.5, 5))
    sns.barplot(data=frames["high_city"], x="city_rank", y="user_count", hue="city_rank", dodge=False, palette="crest", legend=False, ax=ax)
    ax.set_title("High-Value User Portrait: Top Cities")
    ax.set_xlabel("City Rank")
    ax.set_ylabel("High-Value User Count")
    outputs.append(_save(fig, "portrait_high_value_city.png"))

    fig, ax = plt.subplots(figsize=(8.5, 5))
    sns.barplot(data=frames["high_member"], x="member_level_en", y="user_count", hue="member_level_en", dodge=False, palette="viridis", legend=False, ax=ax)
    ax.set_title("High-Value User Portrait: Member Levels")
    ax.set_xlabel("Member Level")
    ax.set_ylabel("High-Value User Count")
    outputs.append(_save(fig, "portrait_high_value_member.png"))

    member_rfm = frames["member_rfm"].copy()
    member_rfm["rate_pct"] = (member_rfm["high_value_rate"] * 100).round(2)
    fig, ax = plt.subplots(figsize=(8.5, 5))
    sns.barplot(data=member_rfm, x="member_level_en", y="rate_pct", hue="member_level_en", dodge=False, palette="magma", legend=False, ax=ax)
    ax.set_title("Portrait × RFM: High-Value Rate by Member Level")
    ax.set_xlabel("Member Level")
    ax.set_ylabel("High-Value Rate (%)")
    outputs.append(_save(fig, "portrait_rfm_high_value_rate.png"))

    age_rfm = frames["age_rfm"].copy()
    age_rfm["rate_pct"] = (age_rfm["churn_rate"] * 100).round(2)
    fig, ax = plt.subplots(figsize=(8.5, 5))
    sns.barplot(data=age_rfm, x="age_group", y="rate_pct", hue="age_group", dodge=False, palette="rocket", legend=False, ax=ax)
    ax.set_title("Portrait × RFM: Churn Risk by Age Group")
    ax.set_xlabel("Age Group")
    ax.set_ylabel("Churn Risk Rate (%)")
    outputs.append(_save(fig, "portrait_rfm_churn_by_age.png"))

    cluster_gender = frames["cluster_gender"].copy()
    cluster_gender["share_pct"] = (cluster_gender["female_share"] * 100).round(2)
    fig, ax = plt.subplots(figsize=(8.5, 5))
    sns.barplot(data=cluster_gender, x="cluster_name_en", y="share_pct", hue="cluster_name_en", dodge=False, palette="Set2", legend=False, ax=ax)
    ax.set_title("Portrait × KMeans: Female Share by Cluster")
    ax.set_xlabel("Cluster")
    ax.set_ylabel("Female Share (%)")
    ax.tick_params(axis="x", rotation=15)
    outputs.append(_save(fig, "portrait_kmeans_female_share.png"))

    heatmap_df = frames["city_cluster"].set_index("cluster_name_en")
    fig, ax = plt.subplots(figsize=(9, 5.8))
    sns.heatmap(heatmap_df, annot=True, fmt="d", cmap="YlGnBu", ax=ax)
    ax.set_title("Portrait × KMeans: City Concentration by Cluster")
    ax.set_xlabel("City Rank")
    ax.set_ylabel("Cluster")
    outputs.append(_save(fig, "portrait_kmeans_city_heatmap.png"))

    return outputs


def export_index(files: list[Path]) -> None:
    index = {"generated_dir": str(OUTPUT_DIR), "files": [f.name for f in files]}
    (OUTPUT_DIR / "figure_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    md_lines = ["# Figure Index", ""]
    for file in files:
        md_lines.append(f"- [{file.name}](</{file.as_posix()}>)")
    (OUTPUT_DIR / "figure_index.md").write_text("\n".join(md_lines), encoding="utf-8")


def main() -> None:
    files: list[Path] = []
    files.extend(export_mysql_table_counts())
    files.extend(export_mysql_query_figures())
    files.extend(export_kmeans_figures())
    files.extend(export_advanced_portrait_figures())
    export_index(files)
    print(str(OUTPUT_DIR))


if __name__ == "__main__":
    main()
