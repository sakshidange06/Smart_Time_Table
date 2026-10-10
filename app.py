import sys
from pathlib import Path
from pypdf import PdfReader
from langchain_core.prompts import ChatPromptTemplate

# Import your configured Groq LLM instance from llm.py
from llm import llm

# Default credentials
VALID_USERNAME = "admin"
VALID_PASSWORD = "password123"

def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 150) -> list[str]:
    """Splits text into overlapping chunks for LLM context windows."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

def extract_pdf_text(pdf_path: str) -> str:
    """Reads PDF and retrieves plain text."""
    path = Path(pdf_path.strip("'\""))
    if not path.is_file():
        raise FileNotFoundError(f"File not found at path: {path}")
    
    reader = PdfReader(path)
    extracted_text = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            extracted_text += text + "\n"
    return extracted_text

# ---------------- LOGIN LOGIC ----------------
print("=== Welcome to Smart Timetable AI ===")
username = input("Username: ").strip()
password = input("Password: ").strip()

if username == VALID_USERNAME and password == VALID_PASSWORD:
    print("\nLogin successful!\n")
else:
    print("\nInvalid username or password. Exiting program.")
    sys.exit(1)

# ---------------- OPERATION SELECTION ----------------
choice = input("Please choose the operation:\n 1 for Quick Revision (Quiz)\n 2 for Create Smart Time Table\nEnter choice (1 or 2): ").strip()

if choice == "1":
    # Option 1: Quick Revision & Quiz Generator
    pdf_path = input("\nEnter path to your Syllabus PDF: ").strip()
    try:
        print("\nReading syllabus PDF...")
        raw_text = extract_pdf_text(pdf_path)
        
        if not raw_text.strip():
            print("\nError: No text could be extracted from this PDF.")
            sys.exit(1)
            
        chunks = chunk_text(raw_text)
        
        print("\nSyllabus read successfully! Generating your quiz via Groq...")
        
        # Define prompt template for quiz generation
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an expert AI tutor. Based on the syllabus text provided, generate a structured 5-question multiple-choice quiz with answer keys to help the student revise."),
            ("human", "Here is a section of the syllabus:\n\n{syllabus_chunk}")
        ])
        
        # Create the LCEL chain (Prompt | LLM)
        chain = prompt | llm
        
        # Invoke the chain using the first text chunk
        response = chain.invoke({"syllabus_chunk": chunks[0]})
        
        print("\n" + "="*50)
        print("🎯 QUICK REVISION QUIZ")
        print("="*50)
        print(response.content)
        print("="*50)
        
    except Exception as e:
        print(f"\nError processing PDF: {e}")

else:
    # Option 2: Create Smart Time Table (Placeholder for your timetable logic)
    pdf_path = input("\nEnter path to your College/School Timetable PDF: ").strip()
    try:
        raw_text = extract_pdf_text(pdf_path)
        print("\nTimetable read successfully!")
        
        # User routine information gathering
        wake_time = input("Waking up time: ").strip()
        sleep_time = input("Sleeping time: ").strip()
        dinner_time = input("Dinner time: ").strip()
        travel_timestamps = input("If you travel, please tell the timestamps: ").strip()
        
        print("\nSuccessfully received data and now creating time table for you!")
        
    except Exception as e:
        print(f"\nError reading timetable PDF: {e}")