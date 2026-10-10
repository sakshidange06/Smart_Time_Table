import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()

groq_api_key = os.getenv("GROQ_API_KEY")

if not groq_api_key:
    raise ValueError("GROQ_API_KEY is not set in the .env file.")

# Initialize the Groq LLM instance
llm = ChatGroq(
    temperature=0.3,
    model_name="openai/gpt-oss-20b",
    groq_api_key=groq_api_key
)