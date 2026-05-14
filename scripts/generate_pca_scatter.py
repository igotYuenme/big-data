from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.spark_kmeans_rfm import build_features_pandas


OUTPUT_DIR = PROJECT_ROOT / "docs" / "figures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR = PROJECT_ROOT / "docs" / "outputs"


plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.unicode_minus"] = False
sns.set_theme(style="whitegrid")

CLUSTER_NAME_EN = {
    "高价值核心群体": "High Value Core",
    "流失风险群体": "Churn Risk",
    "潜力成长群体": "Growth Potential",
    "中等价值稳定群体": "Stable Mid-Value",
    "一般活跃群体": "Active General",
}


def standardize(x: np.ndarray) -> np.ndarray:
    mean = x.mean(axis=0, keepdims=True)
    std = x.std(axis=0, keepdims=True)
    std[std == 0] = 1.0
    return (x - mean) / std


def pca_2d(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    # SVD-based PCA avoids threadpool issues seen with sklearn on this machine.
    u, s, vt = np.linalg.svd(x, full_matrices=False)
    coords = x @ vt[:2].T
    var = (s ** 2) / max(x.shape[0] - 1, 1)
    ratio = var / var.sum()
    return coords[:, :2], ratio[:2]


def main() -> None:
    summary = pd.read_json(OUTPUTS_DIR / "final_kmeans_summary.json", typ="series")
    feature_cols = list(summary["feature_columns"])
    labels = pd.read_csv(OUTPUTS_DIR / "final_kmeans_cluster_labels.csv")
    cluster_summary = pd.read_csv(OUTPUTS_DIR / "final_kmeans_cluster_summary.csv")

    pdf = build_features_pandas()
    merged = pdf.merge(labels, on="user_id", how="inner")
    cluster_name_map = {
        int(row["cluster"]): CLUSTER_NAME_EN.get(row["cluster_name"], row["cluster_name"])
        for _, row in cluster_summary.iterrows()
    }
    merged["cluster_name_en"] = merged["cluster"].map(cluster_name_map)

    x = merged[feature_cols].astype(float).fillna(0.0).to_numpy()
    x = standardize(x)
    coords, ratio = pca_2d(x)
    merged["pca1"] = coords[:, 0]
    merged["pca2"] = coords[:, 1]

    fig, ax = plt.subplots(figsize=(10, 7))
    sns.scatterplot(
        data=merged,
        x="pca1",
        y="pca2",
        hue="cluster_name_en",
        palette="Set2",
        alpha=0.68,
        s=28,
        ax=ax,
    )
    ax.set_title("PCA Scatter Plot of User Clusters")
    ax.set_xlabel(f"Principal Component 1 ({ratio[0] * 100:.2f}% variance)")
    ax.set_ylabel(f"Principal Component 2 ({ratio[1] * 100:.2f}% variance)")
    ax.legend(title="Cluster", bbox_to_anchor=(1.02, 1), loc="upper left")
    fig.tight_layout()
    out = OUTPUT_DIR / "kmeans_pca_scatter.png"
    fig.savefig(out, dpi=220, bbox_inches="tight")
    plt.close(fig)
    print(out)


if __name__ == "__main__":
    main()
