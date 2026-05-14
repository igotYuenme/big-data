# Spark / KMeans 模块说明

## 文件说明

- `scripts/spark_kmeans_rfm.py`：Spark KMeans 聚类、轮廓系数评估、RFM 对照分析脚本

## 当前实现逻辑

1. 读取 `users.csv`、`orders.csv`、`user_behaviors.csv`
2. 构造用户特征：
   - RFM 基础特征
   - 浏览、点击、收藏、加购、购买次数
   - 平均停留时长
   - 会员等级分值
3. 使用 Spark MLlib KMeans 进行聚类
4. 使用 `ClusteringEvaluator` 计算轮廓系数
5. 输出 RFM 标签与 KMeans 聚类结果对照表

## 运行方式

如果环境已安装 `pyspark`：

```powershell
conda activate yolo_env
python scripts/spark_kmeans_rfm.py --k 4
```

输出文件会生成在 `docs/outputs/` 下。

## 当前环境说明

当前工作环境里尚未检测到 `pyspark`，因此脚本内置了降级逻辑：

- 若已安装 `pyspark`：执行完整 Spark KMeans
- 若未安装 `pyspark`：至少导出特征表和 RFM 标签文件，方便后续继续补跑
