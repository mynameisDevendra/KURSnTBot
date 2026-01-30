import os
import json
import logging
import io
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
# Ensure 'credentials.json' is in your project folder
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json' 

def get_drive_service():
    """Authenticates and returns the Drive service."""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        logging.error("❌ credentials.json not found! Cannot connect to Drive.")
        return None
        
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def download_file_from_drive(filename):
    """
    Robust search that works even if extensions (.pdf) 
    or trailing spaces are missing/mismatched in Drive.
    """
    service = get_drive_service()
    if not service: return None
    
    # 1. Clean the filename: Remove .pdf extension and extra spaces
    # Example: "Annexure II Drawings.pdf" BECOMES "Annexure II Drawings"
    clean_name = os.path.splitext(filename)[0].strip()
    
    logging.info(f"🔍 Searching Drive for file containing: '{clean_name}'")

    # 2. Use 'contains' for a wider search (Fuzzy Match)
    # We escape single quotes just in case the filename has them
    safe_name = clean_name.replace("'", "\\'")
    
    results = service.files().list(
        q=f"name contains '{safe_name}' and trashed = false",
        pageSize=1, 
        fields="files(id, name)"
    ).execute()
    items = results.get('files', [])

    if not items:
        logging.warning(f"⚠️ Search failed for '{clean_name}'. Checking strict match...")
        # Fallback: Try the original filename just in case
        results_strict = service.files().list(
            q=f"name = '{filename}' and trashed = false",
            pageSize=1, fields="files(id, name)"
        ).execute()
        items = results_strict.get('files', [])
        
        if not items:
            logging.error(f"❌ File not found in Drive: {filename}")
            return None

    found_file = items[0]
    file_id = found_file['id']
    real_name = found_file['name']
    
    logging.info(f"✅ Found match in Drive: '{real_name}' (ID: {file_id})")
    
    # 3. Download the file stream
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    
    done = False
    while done is False:
        status, done = downloader.next_chunk()

    # 4. Save to local temp file
    local_path = f"temp_{filename}"
    with open(local_path, 'wb') as f:
        f.write(fh.getbuffer())
        
    return local_path

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

# --- LOGIC: /ask Command (Text + Diagram) ---
async def ask_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("❓ Please provide a question. Example: /ask circuit diagram of point machine")
        return

    try:
        # Load the FAISS index
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
        index_path = os.path.join(os.getcwd(), "faiss_index")
        
        if not os.path.exists(index_path):
            await update.message.reply_text("❌ Error: 'faiss_index' folder not found. Please upload it.")
            return

        # Load Local Index
        db = FAISS.load_local(index_path, embeddings, allow_dangerous_deserialization=True)
        
        # Search for top 3 relevant sections
        docs = db.similarity_search(query, k=3)
        
        if not docs:
            await update.message.reply_text("⚠️ No relevant info found in the manuals.")
            return

        # Extract metadata
        sources = []
        for d in docs:
            source_file = os.path.basename(d.metadata.get('source', 'Unknown Manual'))
            page_num = d.metadata.get('page', 'N/A')
            sources.append(f"📄 {source_file} (Page {page_num})")
        
        unique_sources = "\n".join(list(set(sources)))
        context_text = "\n".join([d.page_content for d in docs])

        # Generate Text Answer (Gemini 2.0)
        model = genai.GenerativeModel('gemini-2.0-flash')
        rag_prompt = f"Using ONLY this signaling manual text, answer the question: {query}\n\nContext: {context_text}"
        response = model.generate_content(rag_prompt)
        
        final_reply = f"📖 **Manual Answer:**\n\n{response.text}\n\n📍 **Sources Found:**\n{unique_sources}"
        await update.message.reply_text(final_reply)

        # --- DIAGRAM FETCHING LOGIC ---
        # 1. Check if user asked for a visual
        is_diagram_request = any(word in query.lower() for word in ["diagram", "drawing", "circuit", "figure", "image", "sketch", "layout"])
        
        if is_diagram_request and docs:
            best_doc = docs[0] # Assume the best match has the diagram
            full_source = best_doc.metadata.get('source', '')
            filename = os.path.basename(full_source)
            # FAISS pages are 0-indexed, so we add 1 for the real page number
            page_num = int(best_doc.metadata.get('page', 0)) + 1 

            status_msg = await update.message.reply_text(f"⏳ **Diagram Requested:** Searching for '{filename}' in Drive...")

            try:
                # 2. Download specific PDF from Drive
                local_pdf = download_file_from_drive(filename)
                
                if local_pdf:
                    await status_msg.edit_text(f"⏳ File found. Extracting Page {page_num}...")
                    
                    # 3. Convert Page to Image
                    # 'first_page' and 'last_page' are 1-indexed in pdf2image
                    images = convert_from_path(local_pdf, first_page=page_num, last_page=page_num)
                    
                    if images:
                        img_path = "temp_diagram.jpg"
                        images[0].save(img_path, 'JPEG')
                        
                        # 4. Send Image
                        await update.message.reply_photo(
                            photo=open(img_path, 'rb'), 
                            caption=f"📍 **Diagram Source:** {filename} (Page {page_num})"
                        )
                        
                        # Cleanup Image
                        os.remove(img_path)
                    
                    # Cleanup PDF
                    os.remove(local_pdf)
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=status_msg.message_id)
                else:
                    await status_msg.edit_text(f"⚠️ I found the text in **{filename}**, but I could not find that file in your connected Google Drive to show the picture.")

            except Exception as e:
                logging.error(f"Drive/Image Error: {e}")
                await status_msg.edit_text("❌ Failed to retrieve the diagram. (Check logs for details)")

    except Exception as e:
        logging.error(f"Search Error: {e}")
        await update.message.reply_text("❌ Critical Error during manual search.")

# --- LOGIC: Photo Analysis (Multimodal) ---
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

# --- LOGIC: Message Monitoring (With Memory) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    user_text = update.message.text
    user_name = update.message.from_user.first_name

    # --- MEMORY BLOCK START ---
    if 'conversation_history' not in context.chat_data:
        context.chat_data['conversation_history'] = []

    new_entry = f"{user_name}: {user_text}"
    context.chat_data['conversation_history'].append(new_entry)

    if len(context.chat_data['conversation_history']) > 5:
        context.chat_data['conversation_history'].pop(0)

    history_text = "\n".join(context.chat_data['conversation_history'])
    # --- MEMORY BLOCK END ---

    try:
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        prompt = f"""
        {SYSTEM_PROMPT}
        
        CONTEXT (Recent Conversation):
        {history_text}
        
        TASK:
        Identify if the LATEST message ("{user_text}") completes a transaction or provides missing details.
        If the latest message is a number (e.g., "100"), look back at the history to find the item it refers to.
        Return the JSON for the complete transaction.
        """
        
        response = model.generate_content(prompt)
        ai_output = response.text.strip().replace("```json", "").replace("```", "")

        if "IGNORE" not in ai_output:
            try:
                data = json.loads(ai_output)
                if data.get('item'):
                    save_to_db(user_name, data, user_text)
                    logging.info(f"✅ Stored data for: {data.get('item')}")
                    
                    if data.get('category') == 'issue' and data.get('sentiment', 5) <= 2:
                        await update.message.reply_text(f"⚠️ **High Priority logged at {data.get('location')}**")
            except json.JSONDecodeError:
                pass 
                
    except Exception as e:
        logging.error(f"Monitoring error: {e}")

# --- MAIN BOOTSTRAP ---
if __name__ == '__main__':
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("ask", ask_manual))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 Railway AI Agent is LIVE and MONITORING...")
    app.run_polling()