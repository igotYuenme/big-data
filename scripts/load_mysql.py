from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "docs" / "data"
SCHEMA_PATH = PROJECT_ROOT / "docs" / "mysql" / "schema.sql"


TABLE_FILES = {
    "users": DATA_DIR / "users.csv",
    "products": DATA_DIR / "products.csv",
    "orders": DATA_DIR / "orders.csv",
    "user_behaviors": DATA_DIR / "user_behaviors.csv",
}


def _normalize_datetime(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    return out


def _normalize_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def load_dataframe(table_name: str) -> pd.DataFrame:
    df = pd.read_csv(TABLE_FILES[table_name])
    if table_name == "users":
        df = _normalize_datetime(df, ["registration_date"])
        df = _normalize_numeric(df, ["age", "account_balance", "credit_score"])
    elif table_name == "products":
        df = _normalize_numeric(df, ["price", "sales_count"])
    elif table_name == "orders":
        df = _normalize_datetime(df, ["order_date", "delivery_date", "receive_date"])
        df = _normalize_numeric(
            df,
            [
                "quantity",
                "unit_price",
                "total_amount",
                "discount",
                "actual_payment",
                "review_score",
            ],
        )
    elif table_name == "user_behaviors":
        df = _normalize_datetime(df, ["behavior_time"])
        df = _normalize_numeric(df, ["duration_seconds"])
    return df


def build_engine(args: argparse.Namespace):
    url = (
        f"mysql+pymysql://{args.user}:{args.password}@{args.host}:{args.port}/{args.database}"
        "?charset=utf8mb4"
    )
    return create_engine(url, future=True)


def init_database(args: argparse.Namespace) -> None:
    admin_url = f"mysql+pymysql://{args.user}:{args.password}@{args.host}:{args.port}/?charset=utf8mb4"
    admin_engine = create_engine(admin_url, future=True)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]
    with admin_engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def load_tables(args: argparse.Namespace) -> None:
    engine = build_engine(args)
    for table_name in ["users", "products", "orders", "user_behaviors"]:
        df = load_dataframe(table_name)
        df.to_sql(table_name, engine, if_exists="append", index=False, method="multi", chunksize=1000)
        print(f"loaded {table_name}: {len(df)} rows")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load CSV data into MySQL.")
    parser.add_argument("--host", default=os.environ.get("MYSQL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MYSQL_PORT", "3306")))
    parser.add_argument("--user", default=os.environ.get("MYSQL_USER", "root"))
    parser.add_argument("--password", default=os.environ.get("MYSQL_PASSWORD", "root"))
    parser.add_argument("--database", default=os.environ.get("MYSQL_DATABASE", "taobao_analysis"))
    parser.add_argument("--init-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    init_database(args)
    print("database initialized")
    if not args.init_only:
        load_tables(args)


if __name__ == "__main__":
    main()
