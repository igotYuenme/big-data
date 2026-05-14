-- =============================================================================
-- 淘宝用户行为数据清洗脚本（HiveQL）
-- 数据库：taobao
-- 说明：对原始表去重、缺失值过滤、类型规范化、行为编码统一，供分析与可视化使用。
-- 执行示例：hive -f data_cleaning.sql
-- 注意：若集群无建表权限，可只运行下方「仅查询验收」部分的 SELECT 做逻辑验证。
--
-- 【CSV → HDFS 前置条件】分析侧使用 LazySimpleSerDe + 英文逗号分隔时，请保证：
--   · UTF-8 无 BOM（避免首列表头错位）
--   · Unix 换行（LF），避免行尾多余 \r 导致字段粘连
--   · 字段内勿使用未转义的英文逗号；金额列勿混入全角逗号
-- 【与 Python 看板】看板 SQL 已按「用户去重 + 有 pv 用户中的后续行为」统计漏斗/转化率；
--   若原始日志中 buy 与 pv 覆盖人群不一致，务必在清洗层统一行为编码（见下方 CASE）。
-- =============================================================================

USE taobao;

-- -----------------------------------------------------------------------------
-- 步骤1：用户行为表去重
-- 业务含义：同一 behavior_id 在同步或日志回放时可能重复，保留一条即可，避免 PV/UV 虚高。
-- -----------------------------------------------------------------------------
-- 步骤2：缺失值处理
-- 业务含义：user_id / product_id 为空无法关联用户与商品，分析无效，直接剔除。
-- -----------------------------------------------------------------------------
-- 步骤3：行为类型统一映射
-- 业务含义：部分环境使用中文（浏览/加购/收藏/购买），部分使用英文（pv/cart/fav/buy），
--          映射为统一英文编码，便于与漏斗分析、转化率口径一致。
-- -----------------------------------------------------------------------------
-- 步骤4：时间字段类型转换
-- 业务含义：将 behavior_time 规范为 TIMESTAMP，支撑按小时、按日、按周趋势统计。
-- -----------------------------------------------------------------------------

DROP TABLE IF EXISTS taobao.user_behaviors_clean;

CREATE TABLE taobao.user_behaviors_clean
COMMENT '清洗后的用户行为明细：去重、去空、行为编码统一、时间戳规范'
AS
SELECT
    behavior_id,
    TRIM(CAST(user_id AS STRING)) AS user_id,
    TRIM(CAST(product_id AS STRING)) AS product_id,
    CASE
        WHEN LOWER(TRIM(CAST(behavior_type AS STRING))) IN ('pv', '浏览') THEN 'pv'
        WHEN LOWER(TRIM(CAST(behavior_type AS STRING))) IN ('click', '点击') THEN 'click'
        WHEN LOWER(TRIM(CAST(behavior_type AS STRING))) IN ('cart', '加购') THEN 'cart'
        WHEN LOWER(TRIM(CAST(behavior_type AS STRING))) IN ('fav', '收藏') THEN 'fav'
        WHEN LOWER(TRIM(CAST(behavior_type AS STRING))) IN ('buy', '购买') THEN 'buy'
        ELSE LOWER(TRIM(CAST(behavior_type AS STRING)))
    END AS behavior_type,
    CAST(behavior_time AS TIMESTAMP) AS behavior_time,
    CAST(duration_seconds AS BIGINT) AS duration_seconds
FROM (
    SELECT
        behavior_id,
        user_id,
        product_id,
        behavior_type,
        behavior_time,
        duration_seconds,
        ROW_NUMBER() OVER (PARTITION BY behavior_id ORDER BY behavior_time DESC) AS rn
    FROM user_behaviors
    WHERE user_id IS NOT NULL
      AND product_id IS NOT NULL
      AND behavior_id IS NOT NULL
      AND TRIM(CAST(user_id AS STRING)) <> ''
      AND TRIM(CAST(product_id AS STRING)) <> ''
) dedup
WHERE rn = 1;

-- -----------------------------------------------------------------------------
-- 可选：订单表轻量清洗（剔除无主键、无用户、金额为空的异常单）
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS taobao.orders_clean;

CREATE TABLE taobao.orders_clean
COMMENT '清洗后的订单：有效主键与用户、金额非空'
AS
SELECT
    TRIM(CAST(order_id AS STRING)) AS order_id,
    TRIM(CAST(user_id AS STRING)) AS user_id,
    TRIM(CAST(product_id AS STRING)) AS product_id,
    CAST(TRIM(CAST(quantity AS STRING)) AS INT) AS quantity,
    CAST(order_date AS TIMESTAMP) AS order_date,
    order_status,
    payment_method,
    CAST(unit_price AS DOUBLE) AS unit_price,
    CAST(total_amount AS DOUBLE) AS total_amount,
    CAST(discount AS DOUBLE) AS discount,
    CAST(actual_payment AS DOUBLE) AS actual_payment,
    delivery_date,
    receive_date,
    review_score,
    review_content
FROM orders
WHERE order_id IS NOT NULL
  AND user_id IS NOT NULL
  AND product_id IS NOT NULL
  AND actual_payment IS NOT NULL;

-- =============================================================================
-- 仅查询验收（不建表时可用下列语句检查清洗逻辑结果行数与抽样）
-- =============================================================================
-- SELECT behavior_type, COUNT(*) FROM taobao.user_behaviors_clean GROUP BY behavior_type;
-- SELECT COUNT(*) FROM taobao.orders_clean;
