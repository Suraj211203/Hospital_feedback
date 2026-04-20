import os
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import gspread
from google.oauth2.service_account import Credentials
from groq import Groq
from dotenv import load_dotenv

# ── LOAD ENV ─────────────────────────
load_dotenv(".env")

# ── PATH FIX (IMPORTANT) ─────────────
BASE_DIR = Path(__file__).resolve().parent

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# 🔥 FIXED GOOGLE PATH
GOOGLE_CREDS_FILE = BASE_DIR / "google_credentials.json"

# DEBUG
print("API KEY:", GROQ_API_KEY)
print("CREDS PATH:", GOOGLE_CREDS_FILE)
print("FILE EXISTS:", GOOGLE_CREDS_FILE.exists())

# Safety check
if not GROQ_API_KEY:
    raise ValueError("❌ GROQ_API_KEY not found")

if not GOOGLE_CREDS_FILE.exists():
    raise ValueError("❌ google_credentials.json file not found")

GOOGLE_SHEET_NAME = "Hospital Patient Feedback"

# ── SETUP ────────────────────────────
AUDIO_SAVE_DIR = BASE_DIR / "audio_uploads"
AUDIO_SAVE_DIR.mkdir(exist_ok=True)

client = Groq(api_key=GROQ_API_KEY)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── GOOGLE SHEETS ────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def get_sheet():
    creds = Credentials.from_service_account_file(
        GOOGLE_CREDS_FILE, scopes=SCOPES
    )
    client_gs = gspread.authorize(creds)
    return client_gs.open(GOOGLE_SHEET_NAME).sheet1

def ensure_header(sheet):
    if not sheet.get_all_values():
        sheet.append_row([
            "Timestamp", "Patient ID", "Name",
            "Q1 Rating", "Q2 Recommendation",
            "Q3 Improvement", "Original", "Translation", "Audio"
        ])

# ── FASTAPI ──────────────────────────
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SubmissionPayload(BaseModel):
    patient_id: str
    name: str
    q1_rating: str
    q2_recommendation: str
    q3_improvement: str = ""
    original_text: str = ""
    uk_translation: str = ""
    audio_filename: str = ""

@app.get("/")
def root():
    return {"status": "API running 🚀"}

# ── AUDIO UPLOAD ─────────────────────
@app.post("/upload")
async def upload_audio(file: UploadFile = File(...)):

    filename = f"{datetime.now().timestamp()}_{file.filename}"
    path = AUDIO_SAVE_DIR / filename

    with open(path, "wb") as f:
        f.write(await file.read())

    try:
        # 🎤 Transcription
        with open(path, "rb") as f:
            text = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=f
            )

        original_text = text.strip() if isinstance(text, str) else text.text.strip()

        # 🌍 Translation FIXED
        original_text = original_text.strip().replace("\n", " ")
        chat = client.chat.completions.create(
    model="llama-3.1-8b-instant",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a professional translation engine. "
                "Detect the input language automatically and translate it into clear, natural English. "
                "The input may be Hindi, Hinglish, Telugu, French, or any other language. "
                "Always return ONLY the English translation. "
                "Do not explain anything. Do not ask questions. Do not add extra text."
            )
        },
        {
            "role": "user",
            "content": original_text
        }
    ],
    temperature=0
)

        uk_translation = chat.choices[0].message.content.strip()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "filename": filename,
        "original_text": original_text,
        "uk_translation": uk_translation
    }

# ── SUBMIT ───────────────────────────
@app.post("/submit")
async def submit(data: SubmissionPayload):

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