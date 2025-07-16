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

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_modems_imei ON modems(imei);
CREATE INDEX IF NOT EXISTS idx_sims_modem_id ON sims(modem_id);
CREATE INDEX IF NOT EXISTS idx_sms_sim_id ON sms(sim_id);
CREATE INDEX IF NOT EXISTS idx_sms_received_at ON sms(received_at);
