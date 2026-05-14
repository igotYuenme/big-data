from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.load_mysql import init_database, load_tables


QUERY_PATH = PROJECT_ROOT / "docs" / "mysql" / "queries.sql"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "outputs" / "mysql_acceptance"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def build_engine(args: argparse.Namespace):
    url = (
        f"mysql+pymysql://{args.user}:{args.password}@{args.host}:{args.port}/{args.database}"
        "?charset=utf8mb4"
    )
    return create_engine(url, future=True)


def parse_sql_statements(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        cleaned.append(line)
    sql = "\n".join(cleaned)
    return [stmt.strip() for stmt in sql.split(";") if stmt.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MySQL load + acceptance queries.")
    parser.add_argument("--host", default=os.environ.get("MYSQL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MYSQL_PORT", "3306")))
    parser.add_argument("--user", default=os.environ.get("MYSQL_USER", "root"))
    parser.add_argument("--password", default=os.environ.get("MYSQL_PASSWORD", "root"))
    parser.add_argument("--database", default=os.environ.get("MYSQL_DATABASE", "taobao_analysis"))
    parser.add_argument("--skip-load", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.skip_load:
        init_database(args)
        load_tables(args)

    engine = build_engine(args)
    statements = parse_sql_statements(QUERY_PATH)
    outputs: list[dict[str, str | int]] = []
    with engine.connect() as conn:
        for idx, stmt in enumerate(statements, start=1):
            if stmt.lower().startswith("use "):
                conn.execute(text(stmt))
                continue
            df = pd.read_sql(text(stmt), conn)
            filename = f"query_{idx}.csv"
            df.to_csv(OUTPUT_DIR / filename, index=False, encoding="utf-8-sig")
            outputs.append({"query_index": idx, "rows": len(df), "file": filename, "sql": stmt})

    summary = {
        "database": args.database,
        "host": args.host,
        "query_count": len(outputs),
        "outputs": outputs,
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
