"""The UnderCover database, in SQLite."""

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
DROP TABLE IF EXISTS steps;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS sign_offs;
DROP TABLE IF EXISTS decisions;
DROP TABLE IF EXISTS claims;
DROP TABLE IF EXISTS policies;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS handlers;
DROP TABLE IF EXISTS add_ons;
DROP TABLE IF EXISTS plans;
DROP TABLE IF EXISTS documents;
DROP TABLE IF EXISTS settings;

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE documents (name TEXT PRIMARY KEY, content TEXT NOT NULL);

CREATE TABLE plans (
    plan TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    trip_cancellation_max REAL NOT NULL,
    trip_delay_waiting_hours INTEGER NOT NULL,
    trip_delay_max REAL NOT NULL,
    baggage_delay_waiting_hours INTEGER NOT NULL,
    baggage_delay_max REAL NOT NULL,
    baggage_max REAL NOT NULL,
    per_item_limit REAL NOT NULL,
    passport_max REAL NOT NULL,
    emergency_medical_max REAL NOT NULL,
    deductible REAL NOT NULL
);

CREATE TABLE add_ons (
    add_on TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    effect TEXT NOT NULL,
    electronics_per_item_limit REAL
);

CREATE TABLE handlers (
    handler_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    email TEXT NOT NULL,
    can_approve_over_limit INTEGER NOT NULL
);

CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    date_of_birth TEXT NOT NULL,
    address TEXT NOT NULL,
    customer_since TEXT NOT NULL,
    previous_claims TEXT NOT NULL
);

CREATE TABLE policies (
    policy_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers,
    plan TEXT NOT NULL REFERENCES plans,
    add_ons TEXT NOT NULL,
    purchased_on TEXT NOT NULL,
    sold_through TEXT NOT NULL,
    trip TEXT NOT NULL,
    travelers TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE claims (
    claim_id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES policies,
    customer_id TEXT NOT NULL REFERENCES customers,
    claim_type TEXT NOT NULL,
    submitted_on TEXT NOT NULL,
    incident_date TEXT NOT NULL,
    incident_location TEXT NOT NULL,
    summary TEXT NOT NULL,
    story TEXT NOT NULL,
    items TEXT NOT NULL,
    amount_claimed REAL NOT NULL,
    documents TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE decisions (
    claim_id TEXT PRIMARY KEY REFERENCES claims,
    decision TEXT NOT NULL,
    payout REAL NOT NULL,
    reason TEXT NOT NULL,
    policy_section TEXT NOT NULL,
    decided_at TEXT NOT NULL
);

CREATE TABLE sign_offs (
    claim_id TEXT PRIMARY KEY REFERENCES claims,
    handler_id TEXT NOT NULL REFERENCES handlers,
    signed_off_at TEXT NOT NULL
);

CREATE TABLE payments (
    claim_id TEXT PRIMARY KEY REFERENCES claims,
    amount REAL NOT NULL,
    paid_at TEXT NOT NULL
);

CREATE TABLE steps (
    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL REFERENCES claims,
    thread_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def path() -> Path:
    """Return the database file, from UNDERCOVER_DB or the repo root."""
    return Path(os.getenv("UNDERCOVER_DB", str(ROOT / "undercover.db")))


def connect() -> sqlite3.Connection:
    """Open the database, with rows that read like dicts."""
    connection = sqlite3.connect(path(), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_db() -> Iterator[sqlite3.Connection]:
    """Give a request its own connection."""
    connection = connect()
    try:
        yield connection
    finally:
        connection.close()
