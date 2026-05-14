-- =============================
-- 商品热度分析
-- =============================

SELECT
    p.product_id,
    p.product_name,

    COUNT(o.order_id) AS order_count,
    SUM(o.actual_payment) AS total_revenue,

    -- 行为数据
    SUM(CASE WHEN ub.behavior_type = 'pv' THEN 1 ELSE 0 END) AS pv_count,
    SUM(CASE WHEN ub.behavior_type = 'cart' THEN 1 ELSE 0 END) AS cart_count,
    SUM(CASE WHEN ub.behavior_type = 'buy' THEN 1 ELSE 0 END) AS buy_count

FROM products p
LEFT JOIN orders o ON p.product_id = o.product_id
LEFT JOIN user_behaviors ub ON p.product_id = ub.product_id

GROUP BY p.product_id, p.product_name
ORDER BY total_revenue DESC
LIMIT 20;


-- =============================
-- 商品转化率分析
-- =============================

WITH behavior_stats AS (
    SELECT
        product_id,
        SUM(CASE WHEN behavior_type = 'pv' THEN 1 ELSE 0 END) AS pv_count,
        SUM(CASE WHEN behavior_type = 'buy' THEN 1 ELSE 0 END) AS buy_count
    FROM user_behavior_2025
    GROUP BY product_id
)

SELECT
    product_id,
    pv_count,
    buy_count,

    -- 转化率
    buy_count * 1.0 / pv_count AS conversion_rate

FROM behavior_stats
WHERE pv_count > 0
ORDER BY conversion_rate DESC
LIMIT 20;