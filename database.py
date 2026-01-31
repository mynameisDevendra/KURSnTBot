import sqlite3
import os
from datetime import datetime

# FORCE ABSOLUTE PATH so Bot and Dashboard see the same file
DB_NAME = os.path.join(os.getcwd(), "railway_logs.db")

def init_db():
    """Creates the table if it doesn't exist."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT,
            category TEXT,
            item TEXT,
            quantity REAL,
            location TEXT,
            status TEXT,
            sentiment INTEGER,
            raw_text TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    print(f"✅ Database initialized at: {DB_NAME}")

def save_to_db(user_name, data, raw_text):
    """Inserts a new transaction row."""
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''
            INSERT INTO logs (user_name, category, item, quantity, location, status, sentiment, raw_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_name,
            data.get('category'),
            data.get('item'),
            data.get('quantity'),
            data.get('location'),
            data.get('status'),
            data.get('sentiment'),
            raw_text
        ))
        conn.commit()
        conn.close()
        print(f"💾 Saved to DB: {data.get('item')}")
    except Exception as e:
        print(f"❌ Database Save Error: {e}")