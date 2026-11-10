# llm.py
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.runnables import RunnableLambda
from langchain_groq import ChatGroq

# Local computer: load the .env file that sits next to this file.
# Render: there is no .env file, so this does nothing and the values come
# from Render's Environment settings instead (they always take priority).
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")


def _clean(value):
    """Remove accidental spaces, quotes and a pasted 'NAME=' prefix."""
    value = (value or "").strip()
    if "=" in value and value.split("=", 1)[0].isupper():
        value = value.split("=", 1)[1]
    return value.strip().strip('"').strip("'").strip()


def _env_number(name, default, cast):
    """Read a number from the environment, falling back to the default."""
    try:
        return cast(_clean(os.getenv(name)) or default)
    except (TypeError, ValueError):
        return default


MISSING_KEY_MESSAGE = (
    "GROQ_API_KEY is missing. "
    "Locally: add GROQ_API_KEY=your_key to the .env file. "
    "On Render: add GROQ_API_KEY under the Environment tab."
)

groq_api_key = _clean(os.getenv("GROQ_API_KEY"))

# Settings can be changed without editing code (Render -> Environment).
MODEL_NAME = _clean(os.getenv("GROQ_MODEL")) or "openai/gpt-oss-20b"
TIMEOUT_SECONDS = _env_number("GROQ_TIMEOUT", 60, int)       # wait for a reply
MAX_RETRIES = _env_number("GROQ_MAX_RETRIES", 1, int)        # keeps worst case under gunicorn's timeout


def _missing_key(_input):
    raise RuntimeError(MISSING_KEY_MESSAGE)


if groq_api_key:
    llm = ChatGroq(
        model=MODEL_NAME,
        groq_api_key=groq_api_key,
        temperature=0.3,
        max_completion_tokens=8192,
        reasoning_effort="low",
        include_reasoning=False,
        timeout=TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
    )
else:
    # Don't crash the whole website when the key is missing.
    # Login and registration keep working; the quiz and timetable
    # return a clear error message instead.
    print("WARNING:", MISSING_KEY_MESSAGE)
    llm = RunnableLambda(_missing_key)