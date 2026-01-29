import sqlite3

def init_db():
    conn = sqlite3.connect('railway_data.db')
    cursor = conn.cursor()
    # Table for material transactions and flagged issues
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            user_name TEXT,
            category TEXT,
            item TEXT,
            quantity REAL,
            location TEXT,
            status TEXT,
            sentiment INTEGER,
            raw_text TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_to_db(user_name, data, raw_text):
    conn = sqlite3.connect('railway_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO logs (user_name, category, item, quantity, location, status, sentiment, raw_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_name, data['category'], data['item'], data.get('quantity'), 
          data['location'], data['status'], data['sentiment'], raw_text))
    conn.commit()
    conn.close()