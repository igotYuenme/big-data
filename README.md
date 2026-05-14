# big-data

基于淘宝用户消费行为的大数据分析与精准运营研究。

## 项目内容

当前仓库包含以下主要模块：

- `app/`：Flask 可视化页面与分析逻辑
- `docs/data/`：原始 CSV 数据
- `docs/hive/`：Hive 建表、清洗与分析 SQL
- `docs/mysql/`：MySQL 建表、查询与说明文档
- `docs/figures/`：项目图表输出
- `docs/outputs/`：MySQL、KMeans、RFM 等中间结果与结果文件
- `scripts/`：MySQL 导入、Spark/KMeans、图表生成等脚本
- `pyecharts/`：本地兼容层

## 当前已完成能力

- 本地 CSV 模式下的 Flask 页面运行
- Hive 明细读取 + Python 聚合分析
- MySQL 建库建表、真实导入与查询验收
- Spark MLlib KMeans 聚类、K 值对比、特征消融
- 用户画像分析、高价值用户画像、RFM × KMeans 对照分析

## 运行方式

建议先进入 Conda 环境：

```powershell
conda activate yolo_env
python run.py
```

默认使用本地 `docs/data` 下的 CSV 数据。

如果需要使用 Hive：

```powershell
conda activate yolo_env
$env:USE_HIVE="1"
python run.py
```

## 说明

个人课程实验报告文件仅保留在本地，不包含在 GitHub 仓库中。仓库中保留的是项目代码、脚本、结果文件和交接文档。
