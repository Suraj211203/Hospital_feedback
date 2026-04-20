
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import gspread
from google.oauth2.service_account import Credentials
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_CREDS_FILE = BASE_DIR / "google_credentials.json"

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY missing")

AUDIO_SAVE_DIR = BASE_DIR / "audio_uploads"
AUDIO_SAVE_DIR.mkdir(exist_ok=True)

client = Groq(api_key=GROQ_API_KEY)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def get_sheet():
    creds = Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scopes=SCOPES)
    return gspread.authorize(creds).open("Hospital Patient Feedback").sheet1

def ensure_header(sheet):
    if not sheet.get_all_values():
        sheet.append_row([
            "Timestamp","Patient ID","Name",
            "Q1","Q2","Q3","Original","Translation","Audio"
        ])

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class Submission(BaseModel):
    patient_id: str
    name: str
    q1_rating: str
    q2_recommendation: str
    q3_improvement: str = ""
    original_text: str = ""
    uk_translation: str = ""
    audio_filename: str = ""

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    path = AUDIO_SAVE_DIR / file.filename
    with open(path, "wb") as f:
        f.write(await file.read())

    try:
        with open(path, "rb") as f:
            res = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=f
            )

        original = res.text.strip()

        chat = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "Translate to English only."},
                {"role": "user", "content": original}
            ],
            temperature=0
        )

        translated = chat.choices[0].message.content.strip()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "filename": file.filename,
        "original_text": original,
        "uk_translation": translated
    }

@app.post("/submit")
async def submit(data: Submission):
    try:
        sheet = get_sheet()
        ensure_header(sheet)

        sheet.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data.patient_id,
            data.name,
            data.q1_rating,
            data.q2_recommendation,
            data.q3_improvement,
            data.original_text,
            data.uk_translation,
            data.audio_filename
        ])

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success"}
@app.get("/")
def root():
    return {"status": "API running 🚀"}