-- Run:  mysql -u root -p < schema.sql
CREATE DATABASE IF NOT EXISTS expense_tracker
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE expense_tracker;

CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    email         VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    currency      VARCHAR(5)   NOT NULL DEFAULT '₹',
    created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS categories (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    user_id   INT NOT NULL,
    name      VARCHAR(60) NOT NULL,
    color     VARCHAR(7)  NOT NULL DEFAULT '#6c757d',
    UNIQUE KEY uq_user_cat (user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS transactions (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    user_id        INT NOT NULL,
    category_id    INT NULL,
    type           ENUM('expense','income') NOT NULL DEFAULT 'expense',
    amount         DECIMAL(12,2) NOT NULL,
    description    VARCHAR(255) NOT NULL,
    payment_method VARCHAR(30)  NOT NULL DEFAULT 'Cash',
    txn_date       DATE NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_date (user_id, txn_date),
    FOREIGN KEY (user_id)     REFERENCES users(id)      ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS budgets (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    user_id       INT NOT NULL,
    category_id   INT NOT NULL,
    monthly_limit DECIMAL(12,2) NOT NULL,
    UNIQUE KEY uq_user_budget (user_id, category_id),
    FOREIGN KEY (user_id)     REFERENCES users(id)      ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS recurring (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    user_id        INT NOT NULL,
    category_id    INT NULL,
    type           ENUM('expense','income') NOT NULL DEFAULT 'expense',
    amount         DECIMAL(12,2) NOT NULL,
    description    VARCHAR(255) NOT NULL,
    payment_method VARCHAR(30)  NOT NULL DEFAULT 'Cash',
    frequency      ENUM('daily','weekly','monthly','yearly') NOT NULL DEFAULT 'monthly',
    next_date      DATE NOT NULL,
    active         TINYINT(1) NOT NULL DEFAULT 1,
    FOREIGN KEY (user_id)     REFERENCES users(id)      ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS savings_goals (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    user_id        INT NOT NULL,
    name           VARCHAR(100) NOT NULL,
    target_amount  DECIMAL(12,2) NOT NULL,
    saved_amount   DECIMAL(12,2) NOT NULL DEFAULT 0,
    deadline       DATE NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;
