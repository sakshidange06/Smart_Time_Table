import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_groq import ChatGroq

# Local computer: load the .env file that sits next to this file.
# Render: there is no .env file, so this does nothing and the key comes
# from Render's Environment settings instead.
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _clean_key(value):
    """Remove accidental spaces, quotes and a pasted 'GROQ_API_KEY=' prefix."""
    value = (value or "").strip()
    if value.upper().startswith("GROQ_API_KEY="):
        value = value.split("=", 1)[1]
    return value.strip().strip('"').strip("'").strip()


groq_api_key = _clean_key(os.getenv("GROQ_API_KEY"))

if not groq_api_key:
    raise ValueError(
        "GROQ_API_KEY is missing. "
        "Locally: add GROQ_API_KEY=your_key to the .env file. "
        "On Render: add GROQ_API_KEY under Environment settings."
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