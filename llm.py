import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq


# Load environment variables
load_dotenv()


# Get Groq API key from .env
groq_api_key = os.getenv("GROQ_API_KEY")


# Check API key
if not groq_api_key:
    raise ValueError(
        "GROQ_API_KEY is not set in the .env file."
    )


# Create Groq LLM
llm = ChatGroq(
    model="openai/gpt-oss-20b",
    groq_api_key=groq_api_key,
    temperature=0.3,
    max_completion_tokens=8192,
    reasoning_effort="low",
    include_reasoning=False
)