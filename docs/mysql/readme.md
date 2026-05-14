# MySQL 模块说明

## 文件说明

- `schema.sql`：MySQL 建库建表脚本
- `queries.sql`：多表关联查询示例
- `scripts/load_mysql.py`：CSV 导入 MySQL 脚本
- `scripts/run_mysql_acceptance.py`：一键验收脚本，自动导出查询结果 CSV

## 建议环境变量

```powershell
$env:MYSQL_HOST="127.0.0.1"
$env:MYSQL_PORT="3306"
$env:MYSQL_USER="root"
$env:MYSQL_PASSWORD="root"
$env:MYSQL_DATABASE="taobao_analysis"
```

## 初始化数据库

```powershell
conda activate yolo_env
python scripts/load_mysql.py --init-only
```

## 导入全部数据

```powershell
conda activate yolo_env
python scripts/load_mysql.py
```

## 运行关联查询

在 MySQL 客户端中执行：

```sql
SOURCE docs/mysql/queries.sql;
```

## 一键验收并导出结果表

如果 MySQL 服务已经启动，可直接执行：

```powershell
conda activate yolo_env
python scripts/run_mysql_acceptance.py
```

执行完成后，会在 `docs/outputs/mysql_acceptance/` 下生成：

- `query_1.csv`
- `query_2.csv`
- `query_3.csv`
- `query_4.csv`
- `summary.json`

这些文件可以直接作为课程报告和答辩的结果附件。
