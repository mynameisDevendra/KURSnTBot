import os
import json
import logging
from dotenv import load_dotenv
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from database import init_db, save_to_db

# Knowledge Base Imports
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Initialize the Gemini 2.5/3 Client
client = genai.Client(api_key=GEMINI_API_KEY)

# Configuration for Data Extraction
SYSTEM_PROMPT = """
You are a Railway Signaling AI. Extract data from chat into JSON:
{
  "category": "transaction" or "issue",
  "item": "equipment name",
  "quantity": number or null,
  "location": "station/km",
  "status": "short description",
  "sentiment": 1-5
}
If irrelevant, return "IGNORE".
"""

# --- LOGIC: /ask Command (The "Trainer" Check) ---
async def ask_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("❓ Please provide a question. Example: /ask What is relay maintenance?")
        return

    try:
        # Load the FAISS index with proper embeddings
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
        db = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)
        
        # Search for top 3 relevant sections
        docs = db.similarity_search(query, k=3)
        
        # Extract metadata for Source Attribution
        sources = []
        for d in docs:
            source_file = os.path.basename(d.metadata.get('source', 'Unknown Manual'))
            page_num = d.metadata.get('page', 'N/A')
            sources.append(f"📄 {source_file} (Page {page_num})")
        
        unique_sources = "\n".join(list(set(sources)))
        context_text = "\n".join([d.page_content for d in docs])

        # Generate answer using Gemini 2.5/3
        rag_prompt = f"Using ONLY this signaling manual text, answer the question: {query}\n\nContext: {context_text}"
        response = client.models.generate_content(
            model="gemini-2.0-flash", # Or your confirmed working version
            contents=rag_prompt
        )
        
        final_reply = f"📖 **Manual Answer:**\n\n{response.text}\n\n📍 **Sources Found:**\n{unique_sources}"
        await update.message.reply_text(final_reply)
        
    except Exception as e:
        logging.error(f"Search Error: {e}")
        await update.message.reply_text("❌ Could not search manuals. Ensure knowledge_base.py has been run.")

# --- LOGIC: Message Monitoring ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    user_text = update.message.text
    user_name = update.message.from_user.first_name

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=user_text,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json"
            )
        )
        
        ai_output = response.text.strip()

        if "IGNORE" not in ai_output:
            data = json.loads(ai_output)
            save_to_db(user_name, data, user_text)
            print(f"✅ Stored data for: {data.get('item')}")
            
            # Urgent Alert Logic
            if data.get('category') == 'issue' and data.get('sentiment', 5) <= 2:
                await update.message.reply_text(f"⚠️ **High Priority logged at {data.get('location')}**")
    except Exception as e:
        logging.error(f"Monitoring error: {e}")

# --- MAIN BOOTSTRAP ---
if __name__ == '__main__':
    # Initialize SQLite Database
    init_db()
    
    # Initialize Telegram Application
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Register Handlers
    app.add_handler(CommandHandler("ask", ask_manual))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 Railway AI Agent is LIVE and MONITORING...")
    app.run_polling()