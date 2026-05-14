-- =============================
-- 转化漏斗分析
-- =============================

WITH base AS (
    SELECT
        user_id,
        behavior_type
    FROM user_behavior_2025
),

funnel AS (
    SELECT
        COUNT(DISTINCT CASE WHEN behavior_type = 'pv' THEN user_id END) AS pv_users,
        COUNT(DISTINCT CASE WHEN behavior_type = 'click' THEN user_id END) AS click_users,
        COUNT(DISTINCT CASE WHEN behavior_type = 'fav' THEN user_id END) AS fav_users,
        COUNT(DISTINCT CASE WHEN behavior_type = 'cart' THEN user_id END) AS cart_users,
        COUNT(DISTINCT CASE WHEN behavior_type = 'buy' THEN user_id END) AS buy_users
    FROM base
)

SELECT
    pv_users,
    click_users,
    fav_users,
    cart_users,
    buy_users,

    -- 转化率
    click_users * 1.0 / pv_users AS pv_to_click_rate,
    fav_users * 1.0 / click_users AS click_to_fav_rate,
    cart_users * 1.0 / fav_users AS fav_to_cart_rate,
    buy_users * 1.0 / cart_users AS cart_to_buy_rate,

    -- 总转化率
    buy_users * 1.0 / pv_users AS overall_conversion_rate

FROM funnel;