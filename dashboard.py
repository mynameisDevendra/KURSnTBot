import streamlit as st
import sqlite3
import pandas as pd
import os
import sys
import subprocess
import time
# Import the FIXED path
from database import DB_NAME, init_db, save_to_db

st.set_page_config(page_title="Railway Debugger", layout="wide")
st.title("🕵️ Railway Database Debugger")

# 1. Initialize DB immediately
init_db()

# --- DIAGNOSTIC TOOL 1: FILE SYSTEM SPY ---
st.subheader("📂 Server File Check")
st.write(f"Target Database Path: `{DB_NAME}`")

# List all files in the current directory to see duplicates
files = os.listdir(".")
db_files = [f for f in files if ".db" in f]
if db_files:
    st.success(f"✅ Found Database Files: {db_files}")
else:
    st.error("❌ NO .db FILES FOUND IN CURRENT FOLDER!")

# --- DIAGNOSTIC TOOL 2: MANUAL WRITE TEST ---
st.subheader("🧪 Test the Database Connection")
if st.button("Force Write Test Row"):
    test_data = {
        "category": "TEST",
        "item": "Manual Debug Entry",
        "quantity": 99,
        "location": "Dashboard",
        "status": "OK",
        "sentiment": 5
    }
    save_to_db("Admin", test_data, "Manual Click from Dashboard")
    st.toast("Test row written! Click Refresh below.")

# --- DIAGNOSTIC TOOL 3: DATA VIEWER ---
st.subheader("📊 Live Data")

def get_data():
    try:
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("SELECT * FROM logs ORDER BY timestamp DESC", conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Read Error: {e}")
        return pd.DataFrame()

if st.button("🔄 Refresh Data"):
    df = get_data()
else:
    df = get_data()

if not df.empty:
    st.dataframe(df, use_container_width=True)
else:
    st.warning("Database is empty.")

# --- BOT CONTROL ---
st.divider()
st.subheader("🤖 Bot Control")

if "bot_process" not in st.session_state:
    st.session_state.bot_process = None

if st.button("🚀 Start Bot (Background)"):
    if st.session_state.bot_process is None:
        # Pass the unbuffered flag (-u) to see logs instantly
        st.session_state.bot_process = subprocess.Popen([sys.executable, "-u", "bot.py"])
        st.success("Bot Started.")
    else:
        st.warning("Bot is already running.")