import streamlit as st
import sqlite3
import pandas as pd
import os
import sys
import subprocess
import time
# IMPORT PATH FROM SHARED FILE
from database import DB_NAME, init_db

# Page Config
st.set_page_config(page_title="Railway Bot Dashboard", layout="wide")
st.title("🚄 Railway AI Agent Dashboard")

# Initialize DB on load to be safe
init_db()

# ... (Keep your Bot Start/Stop code here) ...

# --- DATABASE VIEWER ---
st.header("📊 Transaction Logs")
st.write(f"📂 Reading Database from: `{DB_NAME}`") # Debugging Line

def get_data():
    try:
        # Use the SAME path as the bot
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("SELECT * FROM logs ORDER BY timestamp DESC", conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"❌ Error reading database: {e}")
        return pd.DataFrame()

if st.button("🔄 Refresh Logs"):
    df = get_data()
else:
    df = get_data()

if df.empty:
    st.info("No logs found. (Try sending 'Sent 5 relays to Station A' in Telegram)")
else:
    st.dataframe(df, use_container_width=True)

# ... (Keep your Drive Debugger code here) ...