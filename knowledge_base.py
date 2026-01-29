import os
import json
import io
import fitz  # PyMuPDF
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

load_dotenv()

# Config
FOLDER_IDS = ["1fa04jAP33VJJLs9PcqHFkwz4lc43vYwM", "1aRBB4gSxrkGv4I-ZQHrJeiYIhQzsaSz7"]
creds_json = json.loads(os.getenv('GOOGLE_DRIVE_CREDENTIALS'))

def sync_from_drive():
    credentials = service_account.Credentials.from_service_account_info(creds_json)
    service = build('drive', 'v3', credentials=credentials)
    all_docs = []
    
    if not os.path.exists("temp_manuals"): os.makedirs("temp_manuals")

    for folder_id in FOLDER_IDS:
        query = f"'{folder_id}' in parents and (mimeType='application/pdf' or mimeType='application/vnd.google-apps.document')"
        results = service.files().list(q=query, fields='files(id, name, mimeType)').execute()
        items = results.get('files', [])

        for item in items:
            file_path = os.path.join("temp_manuals", f"{item['name']}.pdf")
            print(f"📥 Processing: {item['name']}...")
            
            # Export/Download Logic
            if "google-apps" in item['mimeType']:
                request = service.files().export_media(fileId=item['id'], mimeType='application/pdf')
            else:
                request = service.files().get_media(fileId=item['id'])
            
            with io.FileIO(file_path, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done: status, done = downloader.next_chunk()

            # Using PyMuPDF for better technical document parsing
            doc = fitz.open(file_path)
            for page_num, page in enumerate(doc):
                text = page.get_text()
                # Metadata helps the bot "source" the image later
                all_docs.append(Document(page_content=text, metadata={"source": item['name'], "page": page_num + 1}))
            doc.close()

    # Create Index
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    vector_db = FAISS.from_documents(all_docs, embeddings)
    vector_db.save_local("faiss_index")
    print("🚀 Multimodal-ready Brain updated.")

if __name__ == "__main__":
    sync_from_drive()