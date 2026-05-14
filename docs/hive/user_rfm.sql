-- =============================
-- RFM模型构建
-- =============================

WITH rfm_base AS (
    SELECT
        user_id,
        MAX(order_date) AS last_order_date,
        COUNT(*) AS frequency,
        SUM(actual_payment) AS monetary
    FROM orders
    GROUP BY user_id
),

rfm_score AS (
    SELECT
        user_id,
        frequency,
        monetary,

        -- R（最近消费）
        DATEDIFF(CURRENT_DATE, TO_DATE(last_order_date)) AS recency,

        -- 打分（分位数）
        NTILE(5) OVER (ORDER BY DATEDIFF(CURRENT_DATE, TO_DATE(last_order_date)) DESC) AS r_score,
        NTILE(5) OVER (ORDER BY frequency) AS f_score,
        NTILE(5) OVER (ORDER BY monetary) AS m_score
    FROM rfm_base
),

rfm_label AS (
    SELECT
        user_id,
        r_score,
        f_score,
        m_score,

        CASE
            WHEN r_score >=4 AND f_score >=4 AND m_score >=4 THEN '高价值用户'
            WHEN r_score >=3 AND f_score >=3 THEN '潜力用户'
            WHEN r_score <=2 AND f_score <=2 THEN '流失用户'
            ELSE '一般用户'
        END AS user_segment
    FROM rfm_score
)

SELECT
    user_segment,
    COUNT(*) AS user_count
FROM rfm_label
GROUP BY user_segment;