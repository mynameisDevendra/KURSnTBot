import streamlit as st
import sqlite3
import pandas as pd
import os
import sys
import subprocess
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Page Config
st.set_page_config(page_title="Railway Bot Dashboard", layout="wide")
st.title("🚄 Railway AI Agent Dashboard")

# --- DATABASE SETUP (Fixes the "no such table" error) ---
DB_NAME = "railway_logs.db"

def init_db_if_missing():
    """Ensures the database and table exist before we try to read them."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Create the 'logs' table if it doesn't exist
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

# Run this immediately when the app starts
init_db_if_missing()

# --- 1. BOT CONTROL ---
if "bot_process" not in st.session_state:
    st.session_state.bot_process = None

def start_bot():
    if st.session_state.bot_process is None:
        # Start bot.py as a separate process
        st.session_state.bot_process = subprocess.Popen([sys.executable, "bot.py"])
        st.toast("✅ Telegram Bot Started!")
        time.sleep(2) # Give it a moment to initialize
    else:
        st.toast("⚠️ Bot is already running.")

if st.button("🚀 Start Telegram Bot"):
    start_bot()

# --- 2. DATA VIEW ---
st.header("📊 Live Logs")

def get_data():
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql_query("SELECT * FROM logs ORDER BY timestamp DESC", conn)
    except Exception as e:
        st.error(f"Error reading database: {e}")
        df = pd.DataFrame() # Return empty if error
    conn.close()
    return df

# Refresh button
if st.button("🔄 Refresh Logs"):
    df = get_data()
else:
    df = get_data()

if df.empty:
    st.info("No data found yet. Talk to the bot to generate logs!")
else:
    st.dataframe(df, use_container_width=True)

# --- 3. GOOGLE DRIVE DEBUGGER ---
st.header("📂 Drive File Debugger")
st.write("Check if the bot can see your PDF files.")

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'

def get_drive_files():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        return None, "❌ credentials.json not found in root folder!"
    
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('drive', 'v3', credentials=creds)
        
        results = service.files().list(
            pageSize=50, 
            fields="files(id, name)",
            q="trashed = false"
        ).execute()
        return results.get('files', []), None
    except Exception as e:
        return None, str(e)

if st.button("🔍 Check Drive Files"):
    files, error = get_drive_files()
    if error:
        st.error(error)
    elif not files:
        st.warning("⚠️ Connected to Drive, but found NO files. Check sharing permissions.")
    else:
        file_df = pd.DataFrame(files)
        st.success(f"✅ Found {len(files)} files")
        st.dataframe(file_df, use_container_width=True)