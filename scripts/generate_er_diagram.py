from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "docs" / "figures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.unicode_minus"] = False


def draw_entity(ax, x, y, w, h, title, fields, facecolor="#f7fbff", edgecolor="#2b6cb0"):
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.02",
        linewidth=1.6,
        edgecolor=edgecolor,
        facecolor=facecolor,
    )
    ax.add_patch(box)
    ax.text(x + w / 2, y + h - 0.05, title, ha="center", va="center", fontsize=12, fontweight="bold")
    ax.plot([x + 0.02, x + w - 0.02], [y + h - 0.09, y + h - 0.09], color=edgecolor, linewidth=1.0)
    text_y = y + h - 0.14
    for field in fields:
        ax.text(x + 0.03, text_y, field, ha="left", va="center", fontsize=9)
        text_y -= 0.045


def draw_arrow(ax, x1, y1, x2, y2, label="1:N"):
    ax.annotate(
        "",
        xy=(x2, y2),
        xytext=(x1, y1),
        arrowprops=dict(arrowstyle="->", linewidth=1.5, color="#4a5568"),
    )
    ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.02, label, ha="center", va="center", fontsize=9, color="#2d3748")


def main() -> None:
    fig, ax = plt.subplots(figsize=(13, 8))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    draw_entity(
        ax,
        0.06,
        0.55,
        0.26,
        0.32,
        "users",
        [
            "PK user_id",
            "age",
            "gender",
            "province",
            "city",
            "registration_date",
            "member_level",
            "account_balance",
            "credit_score",
        ],
    )

    draw_entity(
        ax,
        0.38,
        0.55,
        0.26,
        0.32,
        "orders",
        [
            "PK order_id",
            "FK user_id",
            "FK product_id",
            "quantity",
            "order_date",
            "order_status",
            "payment_method",
            "actual_payment",
        ],
        facecolor="#fffaf0",
        edgecolor="#c05621",
    )

    draw_entity(
        ax,
        0.70,
        0.55,
        0.24,
        0.28,
        "products",
        [
            "PK product_id",
            "product_name",
            "category",
            "brand",
            "price",
            "sales_count",
        ],
        facecolor="#f0fff4",
        edgecolor="#2f855a",
    )

    draw_entity(
        ax,
        0.30,
        0.12,
        0.40,
        0.28,
        "user_behaviors",
        [
            "PK behavior_id",
            "FK user_id",
            "FK product_id",
            "behavior_type",
            "behavior_time",
            "duration_seconds",
        ],
        facecolor="#faf5ff",
        edgecolor="#6b46c1",
    )

    draw_arrow(ax, 0.32, 0.72, 0.38, 0.72, "1:N")
    draw_arrow(ax, 0.70, 0.69, 0.64, 0.69, "1:N")
    draw_arrow(ax, 0.19, 0.55, 0.41, 0.40, "1:N")
    draw_arrow(ax, 0.81, 0.55, 0.59, 0.40, "1:N")

    ax.text(0.5, 0.95, "Entity-Relationship Diagram of Core Tables", ha="center", va="center", fontsize=16, fontweight="bold")
    ax.text(0.5, 0.91, "Taobao User Consumption Behavior Analysis Project", ha="center", va="center", fontsize=11, color="#4a5568")

    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "mysql_er_diagram.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    print(OUTPUT_DIR / "mysql_er_diagram.png")


if __name__ == "__main__":
    main()
