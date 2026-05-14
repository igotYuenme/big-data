-- =============================================================================
-- 与 docs/data 下 CSV 对齐的 Hive 建表（数据已在 HDFS）
-- =============================================================================
-- HDFS 目录（与 docker namenode 内 put 一致）：
--   /data/taobao/orders/
--   /data/taobao/products/
--   /data/taobao/users/
--   /data/taobao/user_behaviors/
--   /data/taobao/user_features/
--   /data/taobao/product_features/
--   /data/taobao/user_behavior_2025/
--
-- 使用 EXTERNAL TABLE：DROP TABLE 只删元数据，不删 HDFS 上的 CSV。
-- LOCATION 使用完整 URI；若你集群 fs.defaultFS 不是 namenode:9000，请改成
-- 与 core-site.xml 里 fs.defaultFS 一致（或仅用路径 /data/taobao/... 由 Hive 解析）。
-- =============================================================================

USE taobao;

-- -----------------------------------------------------------------------------
-- 1) UserBehavior_2025.csv → /data/taobao/user_behavior_2025/
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS user_behavior_2025;
CREATE EXTERNAL TABLE user_behavior_2025 (
  user_id         STRING,
  product_id      STRING,
  brand           STRING,
  brand_id        INT,
  product_name    STRING,
  category        STRING,
  category_id     BIGINT,
  behavior_type   STRING,
  ts              BIGINT,
  price           DOUBLE
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe'
WITH SERDEPROPERTIES (
  'field.delim' = ',',
  'serialization.format' = ','
)
STORED AS TEXTFILE
LOCATION 'hdfs://namenode:9000/data/taobao/user_behavior_2025'
TBLPROPERTIES ('skip.header.line.count' = '1');


-- -----------------------------------------------------------------------------
-- 2) user_behaviors.csv → /data/taobao/user_behaviors/
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS user_behaviors;
CREATE EXTERNAL TABLE user_behaviors (
  behavior_id       STRING,
  user_id           STRING,
  product_id        STRING,
  behavior_type     STRING,
  behavior_time     STRING,
  duration_seconds  BIGINT
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe'
WITH SERDEPROPERTIES (
  'field.delim' = ',',
  'serialization.format' = ','
)
STORED AS TEXTFILE
LOCATION 'hdfs://namenode:9000/data/taobao/user_behaviors'
TBLPROPERTIES ('skip.header.line.count' = '1');


-- -----------------------------------------------------------------------------
-- 3) products.csv → /data/taobao/products/
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS products;
CREATE EXTERNAL TABLE products (
  product_id    STRING,
  product_name  STRING,
  category      STRING,
  brand         STRING,
  price         DOUBLE,
  sales_count   INT
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe'
WITH SERDEPROPERTIES (
  'field.delim' = ',',
  'serialization.format' = ','
)
STORED AS TEXTFILE
LOCATION 'hdfs://namenode:9000/data/taobao/products'
TBLPROPERTIES ('skip.header.line.count' = '1');


-- -----------------------------------------------------------------------------
-- 4) users.csv → /data/taobao/users/
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS users;
CREATE EXTERNAL TABLE users (
  user_id              STRING,
  age                  INT,
  gender               STRING,
  province             STRING,
  city                 STRING,
  registration_date    STRING,
  member_level         STRING,
  account_balance      DOUBLE,
  credit_score         INT
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe'
WITH SERDEPROPERTIES (
  'field.delim' = ',',
  'serialization.format' = ','
)
STORED AS TEXTFILE
LOCATION 'hdfs://namenode:9000/data/taobao/users'
TBLPROPERTIES ('skip.header.line.count' = '1');


-- -----------------------------------------------------------------------------
-- 5) orders.csv → /data/taobao/orders/
--     HDFS 上文件为标准逗号 CSV（与 docs/data/orders.csv 一致）时，优先用
--     LazySimpleSerDe：与 products 相同，列对齐稳定；分析里已对金额等做 CAST。
--     OpenCSVSerde 在部分环境会出现「相邻数字列粘成一格」的错位，可改回下方注释块。
--     若 review_content 内含英文逗号，需给该字段加引号或改用 OpenCSVSerde。
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS orders;
CREATE EXTERNAL TABLE orders (
  order_id         STRING,
  user_id          STRING,
  product_id       STRING,
  quantity         STRING,
  order_date       STRING,
  order_status     STRING,
  payment_method   STRING,
  unit_price       STRING,
  total_amount     STRING,
  discount         STRING,
  actual_payment   STRING,
  delivery_date    STRING,
  receive_date     STRING,
  review_score     STRING,
  review_content   STRING
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe'
WITH SERDEPROPERTIES (
  'field.delim' = ',',
  'serialization.format' = ','
)
STORED AS TEXTFILE
LOCATION 'hdfs://namenode:9000/data/taobao/orders'
TBLPROPERTIES ('skip.header.line.count' = '1');

-- 可选：OpenCSVSerde（若 LazySimple 建表报 ParseException，再改用 INPUTFORMAT/OUTPUTFORMAT 写法）
-- ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
-- WITH SERDEPROPERTIES ('quoteChar' = '"', 'separatorChar' = ',')
-- STORED AS INPUTFORMAT 'org.apache.hadoop.mapred.TextInputFormat'
-- OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'


-- -----------------------------------------------------------------------------
-- 6) product_features.csv → /data/taobao/product_features/
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS product_features;
CREATE EXTERNAL TABLE product_features (
  product_id          STRING,
  total_revenue       DOUBLE,
  total_sales         INT,
  completed_count     INT,
  cancel_count        INT,
  cart_count          INT,
  favorite_count      INT,
  browse_count        INT,
  click_count         INT,
  conversion_rate     DOUBLE,
  avg_review_score    DOUBLE,
  popularity_score    DOUBLE
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe'
WITH SERDEPROPERTIES (
  'field.delim' = ',',
  'serialization.format' = ','
)
STORED AS TEXTFILE
LOCATION 'hdfs://namenode:9000/data/taobao/product_features'
TBLPROPERTIES ('skip.header.line.count' = '1');


-- -----------------------------------------------------------------------------
-- 7) user_features.csv → /data/taobao/user_features/
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS user_features;
CREATE EXTERNAL TABLE user_features (
  user_id                 STRING,
  total_spent             DOUBLE,
  order_count             DOUBLE,
  completed_orders        DOUBLE,
  avg_order_amount        DOUBLE,
  browse_count            DOUBLE,
  click_count             DOUBLE,
  favorite_count          DOUBLE,
  cart_count              DOUBLE,
  days_since_last_order   INT,
  order_frequency         DOUBLE,
  repurchase_indicator    INT,
  purchase_intent         DOUBLE,
  consumption_level       STRING,
  member_level_score      INT
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe'
WITH SERDEPROPERTIES (
  'field.delim' = ',',
  'serialization.format' = ','
)
STORED AS TEXTFILE
LOCATION 'hdfs://namenode:9000/data/taobao/user_features'
TBLPROPERTIES ('skip.header.line.count' = '1');
