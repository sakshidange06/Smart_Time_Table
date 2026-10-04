import sys
from getpass import getpass
from pathlib import Path
from pypdf import PdfReader

# Default credentials
VALID_USERNAME = "admin"
VALID_PASSWORD = "password123"

def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
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
choice = input("please choose the operation:- 1 for quick revision, 2 for Create Smart time table: ").strip()

if choice == "1":
    # 1 for Quick Revision
    pdf_path = input("\nEnter path to your Syllabus PDF: ")
    try:
        raw_text = extract_pdf_text(pdf_path)
        chunks = chunk_text(raw_text)
        
        # Text is ready to be sent to your LLM/LangChain chain
        print("\nRead successfully")
        
    except Exception as e:
        print(f"\nError processing PDF: {e}")

else:
    # 2 for Create Smart time table
    pdf_path = input("\nEnter path to your College/School Timetable PDF: ")
    try:
        raw_text = extract_pdf_text(pdf_path)
        print("\nunderstand")
        
        # User routine information gathering
        wake_time = input("Waking up time: ").strip()
        sleep_time = input("Sleeping time: ").strip()
        dinner_time = input("Dinner time: ").strip()
        travel_timestamps = input("if you travel then please tell the timestamps: ").strip()
        
        print("\nsuccessfully received data and now creating time table for you!")
        
    except Exception as e:
        print(f"\nError reading timetable PDF: {e}") 