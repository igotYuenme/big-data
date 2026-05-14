"""PyHive 连接：默认连接作业环境 HiveServer2，可通过环境变量覆盖。"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)
_HIVE_BACKEND_DISABLED = False


def get_hive_connection():
    """
    返回 Hive 连接；失败时返回 None（由上层回退到本地 CSV）。

    与 DBeaver「Hadoop / Apache Hive 2」典型配置对应：
    - jdbc:hive2://host:10000/taobao，无用户名密码时，服务端多为 SASL PLAIN（Hive 里常叫 NONE），
      必须用 auth='NONE' + thrift-sasl；若误用 NOSASL（裸 Thrift），易出现 TSocket read 0 bytes。

    环境变量：
    - HIVE_HOST, HIVE_PORT, HIVE_DATABASE
    - HIVE_AUTH：默认 NONE（SASL PLAIN）；若集群明确配置 hive.server2.authentication=NOSASL 可改为 NOSASL
    - HIVE_USERNAME：默认 hive（与常见免密/匿名 JDBC 行为接近）；设为任意非空字符串可覆盖
    """
    host = os.environ.get("HIVE_HOST", "159.75.79.79")
    port = int(os.environ.get("HIVE_PORT", "10000"))
    database = os.environ.get("HIVE_DATABASE", "taobao")
    auth = os.environ.get("HIVE_AUTH", "NONE").strip().upper() or "NONE"

    # 未设置环境变量时用 hive，避免仅依赖 Windows 登录名导致与集群映射不一致
    raw_user = os.environ.get("HIVE_USERNAME")
    if raw_user is None:
        username: Optional[str] = "hive"
    else:
        username = raw_user.strip() or None  # 空字符串 -> None，交给 PyHive 用 getpass.getuser()

    try:
        from pyhive import hive
    except ModuleNotFoundError as exc:
        if exc.name == "pyhive":
            logger.debug("PyHive 未安装，自动切换到本地 CSV。")
        else:
            logger.debug("Hive 客户端导入失败，自动切换到本地 CSV：%s", exc)
        return None
    except Exception as exc:
        logger.warning("Hive 客户端不可用，将使用本地数据：%s", exc)
        return None

    kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "database": database,
        "auth": auth,
        "username": username,
    }
    try:
        return hive.Connection(**kwargs)
    except Exception as exc:
        logger.warning("Hive 连接不可用，将使用本地数据：%s", exc)
        return None


def _hive_database_name() -> str:
    name = (os.environ.get("HIVE_DATABASE") or "taobao").strip()
    if not name or not all(c.isalnum() or c == "_" for c in name):
        return "taobao"
    return name


def configure_hive_session(conn) -> None:
    """
    在 HiveServer2 会话中设置常用参数，减轻 MapRedTask 失败（YARN/MR 异常时 return code 2）的概率。
    若集群禁止客户端 SET，可设环境变量 HIVE_SKIP_SESSION_SETS=1 跳过。

    Docker / 单机伪分布常见：YARN 未就绪导致 MapRedTask return code 2。默认会尝试
    ``SET mapreduce.framework.name=local``（失败则忽略）。生产 YARN 集群若不希望客户端改
    执行模式，请设环境变量 HIVE_SKIP_LOCAL_MR=1 跳过该条。
    """
    if os.environ.get("HIVE_SKIP_SESSION_SETS", "").lower() in ("1", "true", "yes"):
        return
    db = _hive_database_name()
    sets = [
        f"USE {db}",
        "SET hive.exec.mode.local.auto=true",
        "SET hive.fetch.task.conversion=more",
    ]
    cur = conn.cursor()
    for stmt in sets:
        try:
            cur.execute(stmt)
        except Exception as exc:
            if stmt.startswith("USE "):
                logger.warning("Hive %s 失败（未切换库时易出现 Table not found）：%s", stmt, exc)
            else:
                logger.debug("Hive SET 跳过（部分版本不支持）：%s -> %s", stmt, exc)
    if os.environ.get("HIVE_SKIP_LOCAL_MR", "").lower() not in ("1", "true", "yes"):
        try:
            cur.execute("SET mapreduce.framework.name=local")
        except Exception as exc:
            logger.debug("Hive SET mapreduce.framework.name=local 未生效：%s", exc)


def query_dataframe(conn, sql: str):
    """执行 SQL 并返回 pandas DataFrame（列名来自游标描述）。"""
    import pandas as pd

    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    if cur.description is None:
        return pd.DataFrame()
    cols = [c[0].split(".")[-1] for c in cur.description]
    return pd.DataFrame(rows, columns=cols)


def force_local_mode() -> bool:
    if os.environ.get("USE_LOCAL_CSV", "").lower() in ("1", "true", "yes"):
        return True
    # Default to local CSV for stable demos and local experiments.
    return os.environ.get("USE_HIVE", "").lower() not in ("1", "true", "yes")


def is_hive_backend_disabled() -> bool:
    return _HIVE_BACKEND_DISABLED


def mark_hive_backend_disabled(reason: str | None = None) -> None:
    global _HIVE_BACKEND_DISABLED
    if _HIVE_BACKEND_DISABLED:
        return
    _HIVE_BACKEND_DISABLED = True
    if reason:
        logger.warning("Hive 查询失败，已自动切换到本地 CSV：%s", reason)
    else:
        logger.warning("Hive 查询失败，已自动切换到本地 CSV")
