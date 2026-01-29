import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px

# Page Config
st.set_page_config(page_title="Railway S&T Command Center", layout="wide")

def get_data():
    conn = sqlite3.connect('railway_data.db')
    df = pd.read_sql_query("SELECT * FROM logs ORDER BY timestamp DESC", conn)
    conn.close()
    return df

st.title("🚉 Railway S&T AI Command Center")
st.markdown("Real-time insights from Telegram group monitoring.")

# Refresh Data Button
if st.button('🔄 Refresh Data'):
    st.rerun()

df = get_data()

# EMERGENCY DEBUG: Add this line temporarily to see if data exists
st.write(f"Raw data rows found: {len(df)}") 
st.dataframe(df) # This will force show the raw table

if df.empty:
    st.info("Waiting for data from Telegram...")
else:
    # 1. Top Level Metrics
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Logs", len(df))
    col2.metric("Critical Issues", len(df[df['sentiment'] <= 2]))
    col3.metric("Recent Transactions", len(df[df['category'] == 'transaction']))

    # 2. Tabs for Organization
    tab1, tab2, tab3 = st.tabs(["📦 Inventory & Logs", "🛠️ Technical Issues", "📊 Staff Vibe"])

    with tab1:
        st.subheader("Material Movement & Transactions")
        trans_df = df[df['category'] == 'transaction']
        st.dataframe(trans_df[['timestamp', 'user_name', 'item', 'quantity', 'location', 'status']], use_container_width=True)

    with tab2:
        st.subheader("Flagged Technical & General Issues")
        issue_df = df[df['category'].isin(['technical_issue', 'organizational_issue'])]
        
        # Color coding for urgency
        def color_sentiment(val):
            color = 'red' if val <= 2 else 'orange' if val == 3 else 'green'
            return f'color: {color}'
        
        st.table(issue_df[['timestamp', 'category', 'item', 'location', 'status', 'sentiment']].style.applymap(color_sentiment, subset=['sentiment']))

    with tab3:
        st.subheader("Organizational Sentiment Analysis")
        # Trend chart for sentiment
        fig = px.line(df, x='timestamp', y='sentiment', color='category', title="Sentiment Over Time")
        st.plotly_chart(fig, use_container_width=True)
        
        st.write("Recent Raw Feedback:")
        st.dataframe(df[['user_name', 'raw_text', 'sentiment']].head(10))