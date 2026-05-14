CREATE DATABASE IF NOT EXISTS taobao_analysis
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE taobao_analysis;

DROP TABLE IF EXISTS user_behaviors;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    user_id VARCHAR(32) PRIMARY KEY,
    age INT,
    gender VARCHAR(16),
    province VARCHAR(64),
    city VARCHAR(64),
    registration_date DATETIME NULL,
    member_level VARCHAR(32),
    account_balance DECIMAL(12, 2),
    credit_score INT
);

CREATE TABLE products (
    product_id VARCHAR(32) PRIMARY KEY,
    product_name VARCHAR(255),
    category VARCHAR(128),
    brand VARCHAR(128),
    price DECIMAL(12, 2),
    sales_count INT
);

CREATE TABLE orders (
    order_id VARCHAR(32) PRIMARY KEY,
    user_id VARCHAR(32) NOT NULL,
    product_id VARCHAR(32) NOT NULL,
    quantity INT,
    order_date DATETIME NULL,
    order_status VARCHAR(32),
    payment_method VARCHAR(32),
    unit_price DECIMAL(12, 2),
    total_amount DECIMAL(12, 2),
    discount DECIMAL(12, 2),
    actual_payment DECIMAL(12, 2),
    delivery_date DATETIME NULL,
    receive_date DATETIME NULL,
    review_score DECIMAL(4, 2) NULL,
    review_content TEXT NULL,
    INDEX idx_orders_user_id (user_id),
    INDEX idx_orders_product_id (product_id),
    INDEX idx_orders_order_date (order_date),
    CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(user_id),
    CONSTRAINT fk_orders_product FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE user_behaviors (
    behavior_id VARCHAR(32) PRIMARY KEY,
    user_id VARCHAR(32) NOT NULL,
    product_id VARCHAR(32) NOT NULL,
    behavior_type VARCHAR(16),
    behavior_time DATETIME NULL,
    duration_seconds INT,
    INDEX idx_behaviors_user_id (user_id),
    INDEX idx_behaviors_product_id (product_id),
    INDEX idx_behaviors_behavior_time (behavior_time),
    INDEX idx_behaviors_behavior_type (behavior_type),
    CONSTRAINT fk_behaviors_user FOREIGN KEY (user_id) REFERENCES users(user_id),
    CONSTRAINT fk_behaviors_product FOREIGN KEY (product_id) REFERENCES products(product_id)
);
