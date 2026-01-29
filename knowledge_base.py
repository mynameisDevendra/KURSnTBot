import os
import json
import io
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import PyPDFLoader

load_dotenv()

# Config
FOLDER_ID = "1fa04jAP33VJJLs9PcqHFkwz4lc43vYwM"
creds_json = json.loads(os.getenv('GOOGLE_DRIVE_CREDENTIALS'))

def sync_from_drive():
    # 1. Manual Google Drive Connection
    credentials = service_account.Credentials.from_service_account_info(creds_json)
    service = build('drive', 'v3', credentials=credentials)
    
    # 2. List all PDFs in folder
    query = f"'{FOLDER_ID}' in parents and mimeType='application/pdf'"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)', 
                                   includeItemsFromAllDrives=True, supportsAllDrives=True).execute()
    items = results.get('files', [])

    if not items:
        print("❌ No PDFs found in the folder. Please check sharing permissions.")
        return

    all_docs = []
    if not os.path.exists("temp_manuals"): os.makedirs("temp_manuals")

    for item in items:
        print(f"📥 Downloading: {item['name']}...")
        file_id = item['id']
        file_path = f"temp_manuals/{item['name']}"
        
        # Download file content
        request = service.files().get_media(fileId=file_id)
        fh = io.FileIO(file_path, 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        # Load the downloaded PDF
        loader = PyPDFLoader(file_path)
        all_docs.extend(loader.load())

    # 3. Create the Brain (Vector DB)
    if all_docs:
        print(f"✅ Downloaded {len(items)} files. Creating AI Index...")
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = text_splitter.split_documents(all_docs)
        
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
        vector_db = FAISS.from_documents(chunks, embeddings)
        vector_db.save_local("faiss_index")
        print("🚀 SUCCESS! 'KUR Bot' Brain is now fully updated.")
    else:
        print("❌ Failed to process any documents.")

if __name__ == "__main__":
    sync_from_drive()