import os
import json
import logging
import io
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from database import init_db, save_to_db

# Knowledge Base Imports
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# Drive & Image Imports
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseDownload
from pdf2image import convert_from_path

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

# --- GOOGLE DRIVE SETUP ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json' 

def get_drive_service():
    """Authenticates and returns the Drive service."""
    # Check current directory and generic secret paths
    possible_paths = [
        SERVICE_ACCOUNT_FILE,
        f"/etc/secrets/{SERVICE_ACCOUNT_FILE}",
        f"/app/{SERVICE_ACCOUNT_FILE}"
    ]
    
    final_path = None
    for path in possible_paths:
        if os.path.exists(path):
            final_path = path
            break
            
    if not final_path:
        logging.error("❌ credentials.json not found in any standard path!")
        return None
        
    creds = service_account.Credentials.from_service_account_file(
        final_path, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def list_debug_files():
    """Returns a list of the first 10 files the bot CAN see."""
    service = get_drive_service()
    if not service: return ["❌ Error: Could not connect to Drive (Check credentials)."]
    
    try:
        results = service.files().list(
            pageSize=10, 
            fields="files(id, name)",
            q="trashed = false"
        ).execute()
        items = results.get('files', [])
        if not items:
            return ["📂 The Drive folder is EMPTY or not shared with the bot email."]
        return [f"📄 {item['name']}" for item in items]
    except Exception as e:
        return [f"❌ Drive Error: {str(e)}"]

def download_file_from_drive(filename):
    """Robust search for files."""
    service = get_drive_service()
    if not service: return None
    
    # Clean filename
    clean_name = os.path.splitext(filename)[0].strip()
    safe_name = clean_name.replace("'", "\\'")
    
    logging.info(f"🔍 Searching Drive for: '{clean_name}'")

    # SEARCH 1: Fuzzy 'contains'
    results = service.files().list(
        q=f"name contains '{safe_name}' and trashed = false",
        pageSize=1, fields="files(id, name)"
    ).execute()
    items = results.get('files', [])

    # SEARCH 2: Strict match (Fallback)
    if not items:
        results = service.files().list(
            q=f"name = '{filename}' and trashed = false",
            pageSize=1, fields="files(id, name)"
        ).execute()
        items = results.get('files', [])

    if not items:
        return None

    file_id = items[0]['id']
    real_name = items[0]['name']
    
    # Download
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()

    # Use /tmp for Docker compatibility
    local_path = f"/tmp/temp_{filename.replace(' ', '_')}"
    with open(local_path, 'wb') as f:
        f.write(fh.getbuffer())
        
    return local_path

# Configuration for Data Extraction
SYSTEM_PROMPT = """
You are a Railway Signaling AI. Extract data from chat into JSON.
If irrelevant, return "IGNORE".
"""

# --- LOGIC: /ask Command ---
async def ask_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("❓ Please provide a question.")
        return

    try:
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
        index_path = os.path.join(os.getcwd(), "faiss_index")
        
        if not os.path.exists(index_path):
            await update.message.reply_text("❌ Error: 'faiss_index' folder not found.")
            return

        db = FAISS.load_local(index_path, embeddings, allow_dangerous_deserialization=True)
        docs = db.similarity_search(query, k=3)
        
        if not docs:
            await update.message.reply_text("⚠️ No relevant info found.")
            return

        context_text = "\n".join([d.page_content for d in docs])
        sources = "\n".join([f"📄 {d.metadata.get('source')} (Pg {d.metadata.get('page')})" for d in docs])

        model = genai.GenerativeModel('gemini-2.0-flash')
        rag_prompt = f"Using ONLY this text, answer: {query}\n\nContext: {context_text}"
        response = model.generate_content(rag_prompt)
        
        await update.message.reply_text(f"📖 **Answer:**\n{response.text}\n\n📍 **Sources:**\n{sources}")

        # --- DIAGRAM LOGIC ---
        is_diagram_request = any(word in query.lower() for word in ["diagram", "drawing", "circuit", "figure", "image"])
        
        if is_diagram_request and docs:
            best_doc = docs[0]
            full_source = best_doc.metadata.get('source', '')
            filename = os.path.basename(full_source)
            page_num = int(best_doc.metadata.get('page', 0)) + 1 

            status_msg = await update.message.reply_text(f"⏳ Searching Drive for: **{filename}**...")

            try:
                local_pdf = download_file_from_drive(filename)
                
                if local_pdf:
                    await status_msg.edit_text(f"⏳ Downloading & Processing Page {page_num}...")
                    images = convert_from_path(local_pdf, first_page=page_num, last_page=page_num)
                    
                    if images:
                        img_path = f"/tmp/diagram_{page_num}.jpg"
                        images[0].save(img_path, 'JPEG')
                        await update.message.reply_photo(
                            photo=open(img_path, 'rb'), 
                            caption=f"📍 **{filename}** (Page {page_num})"
                        )
                        os.remove(img_path)
                    
                    os.remove(local_pdf)
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=status_msg.message_id)
                else:
                    # --- DEBUG MODE: LIST FILES ---
                    files_seen = list_debug_files()
                    debug_text = "\n".join(files_seen[:10])
                    await status_msg.edit_text(
                        f"❌ **File Not Found.**\n"
                        f"I looked for: `{filename}`\n\n"
                        f"**BUT I only see these files in Drive:**\n"
                        f"{debug_text}\n\n"
                        f"👉 *Please check the names match exactly!*"
                    )

            except Exception as e:
                logging.error(f"Image Error: {e}")
                await status_msg.edit_text(f"❌ Error: {str(e)}")

    except Exception as e:
        logging.error(f"Search Error: {e}")
        await update.message.reply_text("❌ Critical Error.")

# --- RENDER HEALTH CHECK ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.wfile.write(b"Bot Running")

def start_health_check():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE): pass # Placeholder
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE): pass # Placeholder

if __name__ == '__main__':
    init_db()
    threading.Thread(target=start_health_check, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("ask", ask_manual))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🚀 Bot LIVE...")
    app.run_polling()