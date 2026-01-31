import os
import json
import logging
import io
import asyncio
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from database import init_db, save_to_db

# Knowledge Base Imports
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# Drive & Sheets Imports
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseDownload
from pdf2image import convert_from_path

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# --- CONFIGURATION ---
SPREADSHEET_ID = "1JqPBe5aQJDIGPNRs3zVCMUnIU6NDpf8dUXs1oJImNTg" # <--- Your ID

# Configure Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Initialize Gemini
genai.configure(api_key=GEMINI_API_KEY)

# --- GLOBAL VARIABLES (Memory Optimization) ---
# We load the brain ONCE so we don't crash the server repeatedly
VECTOR_DB = None 

# --- GOOGLE SERVICES SETUP ---
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets'
]
SERVICE_ACCOUNT_FILE = 'credentials.json' 

def get_credentials():
    possible_paths = [SERVICE_ACCOUNT_FILE, f"/etc/secrets/{SERVICE_ACCOUNT_FILE}", f"/app/{SERVICE_ACCOUNT_FILE}"]
    for path in possible_paths:
        if os.path.exists(path): return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    return None

def get_drive_service():
    creds = get_credentials()
    return build('drive', 'v3', credentials=creds) if creds else None

def get_sheets_service():
    creds = get_credentials()
    return build('sheets', 'v4', credentials=creds) if creds else None

# --- GOOGLE SHEETS LOGGING ---
def log_to_google_sheet(user_name, data, raw_text):
    try:
        service = get_sheets_service()
        if not service: return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        values = [[user_name, data.get('category'), data.get('item'), data.get('quantity'), data.get('location'), data.get('status'), data.get('sentiment'), raw_text, timestamp]]
        service.spreadsheets().values().append(spreadsheetId=SPREADSHEET_ID, range="Sheet1!A1", valueInputOption="USER_ENTERED", body={'values': values}).execute()
        logging.info(f"✅ Google Sheet Updated.")
    except Exception as e:
        logging.error(f"❌ Sheet Error: {e}")

# --- DRIVE FILE HANDLING ---
def download_file_from_drive(filename):
    service = get_drive_service()
    if not service: return None
    clean_name = os.path.splitext(filename)[0].strip().replace("'", "\\'")
    results = service.files().list(q=f"name contains '{clean_name}' and trashed = false", pageSize=1, fields="files(id, name)").execute()
    items = results.get('files', [])
    if not items: return None
    
    file_id = items[0]['id']
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False: status, done = downloader.next_chunk()

    local_path = f"/tmp/temp_{filename.replace(' ', '_')}"
    with open(local_path, 'wb') as f: f.write(fh.getbuffer())
    return local_path

# --- MEMORY OPTIMIZED SEARCH ---
def load_brain():
    """Loads the FAISS index once at startup."""
    global VECTOR_DB
    index_path = os.path.join(os.getcwd(), "faiss_index")
    if not os.path.exists(index_path):
        logging.error("❌ BRAIN MISSING: 'faiss_index' folder not found.")
        return None
    
    try:
        logging.info("🧠 Loading Knowledge Base into Memory...")
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
        VECTOR_DB = FAISS.load_local(index_path, embeddings, allow_dangerous_deserialization=True)
        logging.info("✅ Brain Loaded Successfully!")
        return VECTOR_DB
    except Exception as e:
        logging.error(f"❌ Failed to load Brain: {e}")
        return None

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple check to see if bot is alive."""
    await update.message.reply_text("🏓 Pong! I am alive and listening.")


# --- LOGIC: /ask Command ---
async def ask_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. DEBUG LOG: Prove we received the command
    logging.info(f"📩 COMMAND RECEIVED: /ask from {update.effective_user.first_name}")
    
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("❓ Please provide a question.")
        return


    # 2. Check if Brain is loaded
    global VECTOR_DB
    if VECTOR_DB is None:
        # Try loading it now if it failed at startup
        VECTOR_DB = load_brain()
        if VECTOR_DB is None:
            await update.message.reply_text("⚠️ **System Error:** Knowledge Base is missing or corrupted.")
            return

    try:
        # 3. Perform Search
        logging.info(f"🔍 Searching for: {query}")
        docs = VECTOR_DB.similarity_search(query, k=3)
        
        if not docs:
            await update.message.reply_text("⚠️ No relevant info found in manuals.")
            return

        context_text = "\n".join([d.page_content for d in docs])
        sources = "\n".join([f"📄 {d.metadata.get('source')} (Pg {d.metadata.get('page')})" for d in docs])

        # 4. Generate Answer
        model = genai.GenerativeModel('gemini-2.0-flash')
        rag_prompt = f"Using ONLY this text, answer: {query}\n\nContext: {context_text}"
        response = model.generate_content(rag_prompt)
        
        await update.message.reply_text(f"📖 **Answer:**\n{response.text}\n\n📍 **Sources:**\n{sources}")

        # 5. Diagram Logic (Simplified)
        if any(w in query.lower() for w in ["diagram", "drawing", "circuit"]):
            filename = os.path.basename(docs[0].metadata.get('source', ''))
            page_num = int(docs[0].metadata.get('page', 0)) + 1
            status_msg = await update.message.reply_text(f"⏳ Fetching diagram: {filename}...")
            
            local_pdf = download_file_from_drive(filename)
            if local_pdf:
                images = convert_from_path(local_pdf, first_page=page_num, last_page=page_num)
                if images:
                    img_path = f"/tmp/diagram.jpg"
                    images[0].save(img_path, 'JPEG')
                    await update.message.reply_photo(photo=open(img_path, 'rb'))
                os.remove(local_pdf)
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=status_msg.message_id)
            else:
                await status_msg.edit_text("❌ Diagram file not found in Drive.")

    except Exception as e:
        logging.error(f"CRASH in /ask: {e}")
        await update.message.reply_text("❌ Error processing request.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE): pass # Simplified for brevity

# --- MESSAGE HANDLER ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or update.message.text.startswith('/'): return
    user_text = update.message.text
    user_name = update.message.from_user.first_name

    # Simple Prompt
    prompt = f"""
    Extract railway transaction data from this text: "{user_text}".
    JSON Format: {{ "category": "transaction", "item": "...", "quantity": 0, "location": "...", "status": "...", "sentiment": 5 }}
    If not a transaction, return "IGNORE". Output ONLY JSON.
    """
    
    try:
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        
        if "IGNORE" not in text:
            data = json.loads(text)
            if data.get('item'):
                save_to_db(user_name, data, user_text)
                log_to_google_sheet(user_name, data, user_text)
                logging.info(f"✅ Logged: {data.get('item')}")
    except:
        pass

# --- MAIN ---
if __name__ == '__main__':
    init_db()
    
    # LOAD BRAIN AT STARTUP (To prevent crashing later)
    load_brain()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("ask", ask_manual))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(CommandHandler("ping", ping))
    
    print("🚀 Railway AI Agent is LIVE...")
    app.run_polling()