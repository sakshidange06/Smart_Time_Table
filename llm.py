import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_groq import ChatGroq

# Always load the .env file that sits next to this file,
# no matter which folder you start the app from.
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Read the key and clean accidental spaces or quotes
groq_api_key = (os.getenv("GROQ_API_KEY") or "").strip().strip('"').strip("'")

if not groq_api_key:
    raise ValueError(
        "GROQ_API_KEY is missing. Add this line to your .env file: "
        "GROQ_API_KEY=your_key_here"
    )

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    groq_api_key=groq_api_key,
    temperature=0.3,
    max_completion_tokens=8192,
    reasoning_effort="low",
    include_reasoning=False,
    timeout=60,       # wait up to 60 seconds for a reply
    max_retries=3,    # retry automatically on connection errors
)