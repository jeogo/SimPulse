-- SimPulse Modem System Database Schema
-- Author: Generated for event-driven modem-SIM management
-- Date: July 16, 2025

-- Create modems table
CREATE TABLE IF NOT EXISTS modems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imei TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create sims table  
CREATE TABLE IF NOT EXISTS sims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    modem_id INTEGER NOT NULL,
    phone_number TEXT,
    balance TEXT,
    info_extracted_at TIMESTAMP,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (modem_id) REFERENCES modems(id)
);

-- Create sms table
CREATE TABLE IF NOT EXISTS sms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sim_id INTEGER NOT NULL,
    sender TEXT NOT NULL,
    message TEXT NOT NULL,
    received_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sim_id) REFERENCES sims(id)
);

-- Create balance_history table for tracking balance changes
CREATE TABLE IF NOT EXISTS balance_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sim_id INTEGER NOT NULL,
    old_balance TEXT,
    new_balance TEXT,
    change_amount TEXT,
    recharge_amount TEXT,
    change_type TEXT DEFAULT 'recharge', -- 'recharge', 'usage', 'manual'
    detected_from_sms BOOLEAN DEFAULT 0,
    sms_sender TEXT,
    sms_content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sim_id) REFERENCES sims(id)
);

-- Create groups table for organizing modems
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name TEXT UNIQUE NOT NULL,
    modem_id INTEGER NOT NULL,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (modem_id) REFERENCES modems(id)
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_modems_imei ON modems(imei);
CREATE INDEX IF NOT EXISTS idx_sims_modem_id ON sims(modem_id);
CREATE INDEX IF NOT EXISTS idx_sms_sim_id ON sms(sim_id);
CREATE INDEX IF NOT EXISTS idx_sms_received_at ON sms(received_at);
CREATE INDEX IF NOT EXISTS idx_balance_history_sim_id ON balance_history(sim_id);
CREATE INDEX IF NOT EXISTS idx_balance_history_created_at ON balance_history(created_at);
CREATE INDEX IF NOT EXISTS idx_groups_modem_id ON groups(modem_id);
CREATE INDEX IF NOT EXISTS idx_groups_name ON groups(group_name);

-- Create telegram_users table for Telegram bot
CREATE TABLE IF NOT EXISTS telegram_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    phone_number TEXT,
    group_id INTEGER,
    status TEXT DEFAULT 'pending', -- pending, approved, rejected, blocked
    verified_balance REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (group_id) REFERENCES groups(id)
);

-- Create balance_verifications table for tracking verification attempts  
CREATE TABLE IF NOT EXISTS balance_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    requested_date TEXT NOT NULL,
    requested_time TEXT NOT NULL,
    result TEXT NOT NULL, -- 'success', 'failed', 'scb_rejected'
    details TEXT,
    settlement_id INTEGER, -- Link to settlement when settled
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (telegram_user_id) REFERENCES telegram_users(id),
    FOREIGN KEY (settlement_id) REFERENCES user_settlements(id)
);

-- Create user_settlements table for individual user settlements
CREATE TABLE IF NOT EXISTS user_settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    settlement_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    period_start_date TIMESTAMP NOT NULL,
    period_end_date TIMESTAMP NOT NULL,
    total_verifications INTEGER NOT NULL,
    total_amount REAL NOT NULL,
    pdf_file_path TEXT,
    admin_telegram_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (telegram_user_id) REFERENCES telegram_users(id)
);

-- Create indexes for telegram bot tables
CREATE INDEX IF NOT EXISTS idx_telegram_users_telegram_id ON telegram_users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_telegram_users_status ON telegram_users(status);
CREATE INDEX IF NOT EXISTS idx_telegram_users_group_id ON telegram_users(group_id);
CREATE INDEX IF NOT EXISTS idx_balance_verifications_telegram_user_id ON balance_verifications(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_balance_verifications_settlement_id ON balance_verifications(settlement_id);
CREATE INDEX IF NOT EXISTS idx_user_settlements_telegram_user_id ON user_settlements(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_user_settlements_settlement_date ON user_settlements(settlement_date);
