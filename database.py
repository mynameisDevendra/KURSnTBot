import sqlite3
import os

# FORCE the database to live in the main app folder
# This prevents it from being created in temporary subfolders
DB_NAME = "/app/railway_logs.db"

def init_db():
    print(f"🔌 Connecting to Database at: {DB_NAME}")
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

def save_to_db(user_name, data, raw_text):
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
        print(f"💾 SUCCESS: Data written to {DB_NAME}")
    except Exception as e:
        print(f"❌ DATABASE ERROR: {e}")