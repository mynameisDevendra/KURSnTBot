import os
import json
import logging
from dotenv import load_dotenv
import google.generativeai as genai
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

# Configure Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Initialize Gemini
genai.configure(api_key=GEMINI_API_KEY)

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
        # Load the FAISS index with robust pathing
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
        index_path = os.path.join(os.getcwd(), "faiss_index")
        
        if not os.path.exists(index_path):
            await update.message.reply_text("❌ Error: 'faiss_index' folder not found on server. Please upload it to GitHub.")
            return

        # Load Local Index
        db = FAISS.load_local(index_path, embeddings, allow_dangerous_deserialization=True)
        
        # Search for top 3 relevant sections
        docs = db.similarity_search(query, k=3)
        
        if not docs:
            await update.message.reply_text("⚠️ No relevant info found in the manuals.")
            return

        # Extract metadata for Source Attribution
        sources = []
        for d in docs:
            source_file = os.path.basename(d.metadata.get('source', 'Unknown Manual'))
            page_num = d.metadata.get('page', 'N/A')
            sources.append(f"📄 {source_file} (Page {page_num})")
        
        unique_sources = "\n".join(list(set(sources)))
        context_text = "\n".join([d.page_content for d in docs])

        # Generate answer using Gemini
        model = genai.GenerativeModel('gemini-1.5-flash')
        rag_prompt = f"Using ONLY this signaling manual text, answer the question: {query}\n\nContext: {context_text}"
        response = model.generate_content(rag_prompt)
        
        final_reply = f"📖 **Manual Answer:**\n\n{response.text}\n\n📍 **Sources Found:**\n{unique_sources}"
        await update.message.reply_text(final_reply)
        
    except Exception as e:
        logging.error(f"Search Error: {e}")
        await update.message.reply_text("❌ Critical Error: Could not search manuals. Check Render logs.")

# --- LOGIC: Photo Analysis (Multimodal) ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo: return

    await update.message.reply_chat_action("typing")
    
    try:
        # 1. Get the highest resolution photo
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        
        # 2. Prepare the prompt
        user_caption = update.message.caption or "Analyze this signaling equipment/diagram. Identify components, faults, or readings."
        
        # 3. Send to Gemini (Multimodal)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content([
            user_caption,
            {'mime_type': 'image/jpeg', 'data': bytes(image_bytes)}
        ])
        
        await update.message.reply_text(f"📷 **Image Analysis:**\n\n{response.text}")
        
    except Exception as e:
        logging.error(f"Photo Error: {e}")
        await update.message.reply_text("❌ Failed to analyze image.")

# --- LOGIC: Message Monitoring ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    user_text = update.message.text
    user_name = update.message.from_user.first_name

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(f"{SYSTEM_PROMPT}\n\nInput Chat: {user_text}")
        
        # Clean up code blocks if the model adds them
        ai_output = response.text.strip().replace("```json", "").replace("```", "")

        if "IGNORE" not in ai_output:
            try:
                data = json.loads(ai_output)
                save_to_db(user_name, data, user_text)
                logging.info(f"✅ Stored data for: {data.get('item')}")
                
                # Urgent Alert Logic
                if data.get('category') == 'issue' and data.get('sentiment', 5) <= 2:
                    await update.message.reply_text(f"⚠️ **High Priority logged at {data.get('location')}**")
            except json.JSONDecodeError:
                pass # Ignore invalid JSON
                
    except Exception as e:
        logging.error(f"Monitoring error: {e}")

# --- MAIN BOOTSTRAP ---
if __name__ == '__main__':
    # 1. Initialize SQLite
    init_db()
    
    # 2. Start Telegram Bot
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Register Handlers
    app.add_handler(CommandHandler("ask", ask_manual))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 Railway AI Agent is LIVE and MONITORING...")
    app.run_polling()