import streamlit as st
import sqlite3
import pandas as pd
import os
import sys
import subprocess
import time
import signal
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Page Config
st.set_page_config(page_title="Railway Bot Dashboard", layout="wide")
st.title("🚄 Railway AI Agent Dashboard")

# --- CONFIGURATION ---
DB_NAME = "railway_logs.db"
LOG_FILE = "bot_console.log"

# --- 1. DATABASE HELPERS ---
def init_db_if_missing():
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

init_db_if_missing()

def insert_test_log():
    """Manually inserts a row to prove the DB works."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        INSERT INTO logs (user_name, category, item, location, status, raw_text)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', ("System", "TEST", "Test Entry", "Dashboard", "OK", "Manual Test Click"))
    conn.commit()
    conn.close()

# --- 2. BOT MANAGEMENT (With Log Capture) ---
if "bot_process" not in st.session_state:
    st.session_state.bot_process = None

def start_bot():
    if st.session_state.bot_process is None:
        # Open a file to capture the bot's output (stdout and stderr)
        with open(LOG_FILE, "w") as log_out:
            # unbuffered (-u) is CRITICAL to see logs instantly
            st.session_state.bot_process = subprocess.Popen(
                [sys.executable, "-u", "bot.py"],
                stdout=log_out,
                stderr=log_out,
                text=True
            )
        st.toast("✅ Bot started with Log Capture!")
    else:
        st.toast("⚠️ Bot is already running.")

def stop_bot():
    if st.session_state.bot_process:
        st.session_state.bot_process.terminate()
        st.session_state.bot_process = None
        st.toast("🛑 Bot Stopped.")

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("🚀 Start Bot"):
        start_bot()
with col2:
    if st.button("🛑 Stop Bot"):
        stop_bot()
with col3:
    if st.button("🧪 Write Test Log to DB"):
        insert_test_log()
        st.toast("Test log inserted. Refresh below!")

# --- 3. CONSOLE LOG VIEWER (Crucial for Debugging) ---
st.subheader("🖥️ Bot Console Output (Live Debugging)")
st.caption("This shows exactly what the bot is doing in the background. If it crashes, the error will appear here.")

if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r") as f:
        log_content = f.read()
        if log_content:
            st.code(log_content[-2000:], language="bash")  # Show last 2000 chars
        else:
            st.info("Bot is running, but hasn't printed anything yet...")
else:
    st.warning("Bot log file not found. Start the bot first.")

st.divider()

# --- 4. DATABASE VIEWER ---
st.subheader("📊 Transaction Logs")

def get_data():
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql_query("SELECT * FROM logs ORDER BY timestamp DESC", conn)
    except Exception as e:
        st.error(f"DB Error: {e}")
        df = pd.DataFrame()
    conn.close()
    return df

if st.button("🔄 Refresh Table"):
    df = get_data()
else:
    df = get_data()

if df.empty:
    st.info("No transaction data yet. Try sending: 'Broken relay at Station X'")
else:
    st.dataframe(df, use_container_width=True)

# --- 5. DRIVE DEBUGGER ---
st.subheader("📂 Google Drive Files")
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'

if st.button("🔍 Check Drive"):
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        st.error("❌ credentials.json missing!")
    else:
        try:
            creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=SCOPES)
            service = build('drive', 'v3', credentials=creds)
            results = service.files().list(
                pageSize=10, fields="files(id, name)", q="trashed = false"
            ).execute()
            files = results.get('files', [])
            st.dataframe(pd.DataFrame(files), use_container_width=True)
        except Exception as e:
            st.error(f"Drive Error: {e}")