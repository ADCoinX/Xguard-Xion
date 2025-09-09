import sqlite3
import os
from datetime import datetime

DB_PATH = "metrics.db"

def ensure_db():
    if not os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            address TEXT,
            duration REAL,
            score INTEGER,
            status TEXT
        )
        """)
        conn.commit()
        conn.close()

ensure_db()

def log_metrics(address: str, duration: float, score: int, status: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO metrics (timestamp, address, duration, score, status) VALUES (?, ?, ?, ?, ?)",
        (datetime.utcnow().isoformat(), address, duration, score, status)
    )
    conn.commit()
    conn.close()

def fetch_metrics():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT timestamp, address, duration, score, status FROM metrics ORDER BY id DESC LIMIT 20")
    rows = c.fetchall()
    conn.close()
    return [
        {"timestamp": r[0], "address": r[1], "duration": r[2], "score": r[3], "status": r[4]}
        for r in rows
    ]