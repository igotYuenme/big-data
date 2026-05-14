USE taobao_analysis;

-- 1. 用户订单金额与画像关联
SELECT
    u.user_id,
    u.gender,
    u.city,
    u.member_level,
    COUNT(o.order_id) AS order_count,
    ROUND(SUM(o.actual_payment), 2) AS total_spent,
    ROUND(AVG(o.actual_payment), 2) AS avg_order_value
FROM users u
JOIN orders o ON u.user_id = o.user_id
GROUP BY u.user_id, u.gender, u.city, u.member_level
ORDER BY total_spent DESC
LIMIT 20;

-- 2. 商品销量、收入与行为曝光关联
SELECT
    p.product_id,
    p.product_name,
    p.category,
    COUNT(DISTINCT o.order_id) AS order_count,
    ROUND(SUM(o.actual_payment), 2) AS total_revenue,
    SUM(CASE WHEN b.behavior_type = '浏览' THEN 1 ELSE 0 END) AS browse_count,
    SUM(CASE WHEN b.behavior_type = '点击' THEN 1 ELSE 0 END) AS click_count,
    SUM(CASE WHEN b.behavior_type = '收藏' THEN 1 ELSE 0 END) AS favorite_count,
    SUM(CASE WHEN b.behavior_type = '加购' THEN 1 ELSE 0 END) AS cart_count
FROM products p
LEFT JOIN orders o ON p.product_id = o.product_id
LEFT JOIN user_behaviors b ON p.product_id = b.product_id
GROUP BY p.product_id, p.product_name, p.category
ORDER BY total_revenue DESC
LIMIT 20;

-- 3. 城市维度用户消费表现
SELECT
    u.city,
    COUNT(DISTINCT u.user_id) AS user_count,
    COUNT(o.order_id) AS order_count,
    ROUND(SUM(o.actual_payment), 2) AS total_revenue,
    ROUND(AVG(o.actual_payment), 2) AS avg_order_value
FROM users u
JOIN orders o ON u.user_id = o.user_id
GROUP BY u.city
ORDER BY total_revenue DESC
LIMIT 20;

-- 4. 用户行为到订单的转化关系
SELECT
    b.user_id,
    SUM(CASE WHEN b.behavior_type = '浏览' THEN 1 ELSE 0 END) AS browse_count,
    SUM(CASE WHEN b.behavior_type = '点击' THEN 1 ELSE 0 END) AS click_count,
    SUM(CASE WHEN b.behavior_type = '收藏' THEN 1 ELSE 0 END) AS favorite_count,
    SUM(CASE WHEN b.behavior_type = '加购' THEN 1 ELSE 0 END) AS cart_count,
    COUNT(DISTINCT o.order_id) AS purchase_count,
    ROUND(SUM(o.actual_payment), 2) AS total_spent
FROM user_behaviors b
LEFT JOIN orders o ON b.user_id = o.user_id AND b.product_id = o.product_id
GROUP BY b.user_id
ORDER BY total_spent DESC, purchase_count DESC
LIMIT 20;
