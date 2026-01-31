import sqlite3
import os
from datetime import datetime
import pytz # <--- Make sure to import this

# --- SMART PATH DETECTION ---
# If we are on Render (Linux), use /app. 
# If we are on Windows (Laptop), use the current folder.
if os.name == 'nt':  # 'nt' means Windows
    DB_NAME = "railway_logs.db"
    print(f"💻 Detected Windows. Using local DB: {os.path.abspath(DB_NAME)}")
else:
    DB_NAME = "/app/railway_logs.db"
    print(f"☁️ Detected Server. Using production DB: {DB_NAME}")

def init_db():
    print(f"🔌 Connecting to Database at: {DB_NAME}")
    
    # Create the connection
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
        
        # FIX: Get current time in India
        IST = pytz.timezone('Asia/Kolkata')
        current_time_ist = datetime.now(IST)
        
        c.execute('''
            INSERT INTO logs (user_name, category, item, quantity, location, status, sentiment, raw_text, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_name,
            data.get('category'),
            data.get('item'),
            data.get('quantity'),
            data.get('location'),
            data.get('status'),
            data.get('sentiment'),
            raw_text,
            current_time_ist  # <--- Saving the IST time explicitly
        ))
        conn.commit()
        conn.close()
        print(f"💾 SUCCESS: Data written to {DB_NAME}")
    except Exception as e:
        print(f"❌ DATABASE ERROR: {e}")