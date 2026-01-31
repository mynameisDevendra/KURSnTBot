import os
import json
import logging
import io
import threading
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
# The ID you provided
SPREADSHEET_ID = "1JqPBe5aQJDIGPNRs3zVCMUnIU6NDpf8dUXs1oJImNTg"

# Configure Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Initialize Gemini
genai.configure(api_key=GEMINI_API_KEY)

# --- GOOGLE SERVICES SETUP ---
# Scopes for BOTH Drive (Reading PDFs) and Sheets (Writing Logs)
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets'
]
SERVICE_ACCOUNT_FILE = 'credentials.json' 

def get_credentials():
    """Finds and loads the credentials file securely."""
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
        
    return service_account.Credentials.from_service_account_file(
        final_path, scopes=SCOPES)

def get_drive_service():
    """Returns the Drive service."""
    creds = get_credentials()
    if not creds: return None
    return build('drive', 'v3', credentials=creds)

def get_sheets_service():
    """Returns the Sheets service."""
    creds = get_credentials()
    if not creds: return None
    return build('sheets', 'v4', credentials=creds)

# --- GOOGLE SHEETS LOGGING ---
def log_to_google_sheet(user_name, data, raw_text):
    """Appends the transaction row to Google Sheets."""
    try:
        service = get_sheets_service()
        if not service: return

        # Prepare the row data
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        values = [[
            user_name,
            data.get('category'),
            data.get('item'),
            data.get('quantity'),
            data.get('location'),
            data.get('status'),
            data.get('sentiment'),
            raw_text,
            timestamp
        ]]
        
        body = {'values': values}
        
        # Append to the sheet
        result = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="Sheet1!A1", # Writes to the first available row in Sheet1
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
        
        logging.info(f"✅ Google Sheet Updated: {result.get('updates').get('updatedCells')} cells.")
        
    except Exception as e:
        logging.error(f"❌ Google Sheet Error: {e}")
        # Detailed debugging tip for logs
        if "403" in str(e):
            logging.error("👉 HINT: You must SHARE the Google Sheet with the Service Account Email!")

# --- DRIVE FILE HANDLING (Robust Search) ---
def list_debug_files():
    """Returns a list of the first 10 files the bot CAN see."""
    service = get_drive_service()
    if not service: return ["❌ Error: Could not connect to Drive."]
    
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

# --- CONFIGURATION FOR DATA EXTRACTION ---
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

# --- LOGIC: Photo Analysis ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo: return

    await update.message.reply_chat_action("typing")
    
    try:
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        
        user_caption = update.message.caption or "Analyze this signaling equipment/diagram. Identify components, faults, or readings."
        
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content([
            user_caption,
            {'mime_type': 'image/jpeg', 'data': bytes(image_bytes)}
        ])
        
        await update.message.reply_text(f"📷 **Image Analysis:**\n\n{response.text}")
        
    except Exception as e:
        logging.error(f"Photo Error: {e}")
        await update.message.reply_text("❌ Failed to analyze image.")

# --- LOGIC: Message Monitoring (Improved Parsing) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    if update.message.text.startswith('/'): return
    
    user_text = update.message.text
    user_name = update.message.from_user.first_name

    # Memory
    if 'conversation_history' not in context.chat_data:
        context.chat_data['conversation_history'] = []
    new_entry = f"{user_name}: {user_text}"
    context.chat_data['conversation_history'].append(new_entry)
    if len(context.chat_data['conversation_history']) > 5:
        context.chat_data['conversation_history'].pop(0)
    history_text = "\n".join(context.chat_data['conversation_history'])

    try:
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        # Enhanced Prompt
        prompt = f"""
        {SYSTEM_PROMPT}
        
        CONTEXT (Recent Conversation):
        {history_text}
        
        TASK:
        Identify if the LATEST message ("{user_text}") implies a transaction, report, or issue.
        - If it is just "Hello" or a question, return "IGNORE".
        - If it is a transaction (e.g. "Sent 5 relays to Dadri"), return the JSON.
        - IMPORTANT: Output ONLY raw JSON. Do not use Markdown formatting like ```json.
        """
        
        response = model.generate_content(prompt)
        ai_output = response.text.strip()

        # Aggressive JSON Cleaning
        if "```json" in ai_output:
            ai_output = ai_output.replace("```json", "").replace("```", "")
        elif "```" in ai_output:
            ai_output = ai_output.replace("```", "")
        ai_output = ai_output.strip()

        if "IGNORE" not in ai_output:
            try:
                data = json.loads(ai_output)
                if data.get('item') and data.get('category'):
                    # 1. Save to Local DB
                    save_to_db(user_name, data, user_text)
                    
                    # 2. Save to Google Sheets
                    log_to_google_sheet(user_name, data, user_text)

                    logging.info(f"✅ Transaction Saved: {data.get('item')}")
                    
                    # Notify user of high priority issues
                    if data.get('category') == 'issue' and data.get('sentiment', 5) <= 2:
                        await update.message.reply_text(f"⚠️ **High Priority logged at {data.get('location')}**")
                else:
                    logging.warning(f"⚠️ Incomplete JSON: {data}")
                    
            except json.JSONDecodeError as e:
                logging.error(f"❌ JSON Parse Error. AI Output: {ai_output}")
                
    except Exception as e:
        logging.error(f"Monitoring error: {e}")

# --- SETUP VERIFICATION ---
def verify_setup():
    """Runs on startup to help you identify missing permissions."""
    print("--- STARTUP VERIFICATION ---")
    creds = get_credentials()
    if creds:
        print(f"ℹ️  SERVICE ACCOUNT EMAIL: {creds.service_account_email}")
        print("👉  ACTION REQUIRED: Copy the email above and SHARE your Google Sheet with it (Editor Access).")
    else:
        print("❌ CRITICAL: Credentials file not found.")
    print("----------------------------")

# --- MAIN BOOTSTRAP ---
if __name__ == '__main__':
    # 1. Initialize DB
    init_db()
    
    # 2. Print the Service Account Email (So you can share the sheet!)
    verify_setup()

    # 3. Start Bot
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("ask", ask_manual))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 Railway AI Agent is LIVE and MONITORING...")
    app.run_polling()