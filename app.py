import os
import csv
import json
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
from pathlib import Path
from pypdf import PdfReader
from langchain_core.prompts import ChatPromptTemplate

# Import your configured Groq LLM instance from llm.py
from llm import llm

app = Flask(__name__, template_folder='.', static_folder='.')

USER_CSV = 'users.csv'
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def init_user_csv():
    """Initializes the CSV file with default admin credentials if it doesn't exist."""
    if not os.path.exists(USER_CSV):
        with open(USER_CSV, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["username", "password"])
            writer.writerow(["admin", "password123"])

init_user_csv()

def verify_credentials(username, password):
    """Checks credentials against the CSV file."""
    if not os.path.exists(USER_CSV):
        init_user_csv()
    with open(USER_CSV, mode='r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["username"] == username and row["password"] == password:
                return True
    return False

def register_new_user(username, password):
    """Registers a new user into the CSV file."""
    if not os.path.exists(USER_CSV):
        init_user_csv()
    
    with open(USER_CSV, mode='r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["username"] == username:
                return False, "Username already exists. Please choose another."
                
    with open(USER_CSV, mode='a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([username, password])
    return True, "Registration successful!"

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
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found at path: {path}")
    
    reader = PdfReader(path)
    extracted_text = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            extracted_text += text + "\n"
    return extracted_text

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if verify_credentials(username, password):
        return jsonify({"success": True, "message": "Login successful!"})
    else:
        return jsonify({"success": False, "message": "Invalid username or password."}), 401

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({"success": False, "message": "Username and password cannot be empty."}), 400

    success, message = register_new_user(username, password)
    if success:
        return jsonify({"success": True, "message": message})
    else:
        return jsonify({"success": False, "message": message}), 400

@app.route('/api/quiz', methods=['POST'])
def generate_quiz():
    if 'pdf' not in request.files:
        return jsonify({"success": False, "message": "No PDF file provided."}), 400
    
    file = request.files['pdf']
    if file.filename == '':
        return jsonify({"success": False, "message": "No selected file."}), 400

    filename = secure_filename(file.filename)
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(pdf_path)

    try:
        raw_text = extract_pdf_text(pdf_path)
        if not raw_text.strip():
            return jsonify({"success": False, "message": "No text could be extracted from this PDF."}), 400
        
        chunks = chunk_text(raw_text)
        syllabus_chunk = chunks[0] if chunks else raw_text[:1500]
        
        # FIXED: Using double curly braces {{ }} to escape literal JSON formatting in the prompt template
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an expert AI tutor. Based on the syllabus text provided, generate a structured 5-question multiple-choice quiz. "
                       "You MUST return ONLY a valid JSON array of objects with no markdown block wrappers (like ```json), structured strictly like this:\n"
                       "[\n  {{\n    \"id\": 1,\n    \"question\": \"Question text?\",\n    \"options\": [\"A) Option 1\", \"B) Option 2\", \"C) Option 3\", \"D) Option 4\"],\n    \"answer\": \"A\"\n  }}\n]"),
            ("human", "Here is a section of the syllabus/notes:\n\n{syllabus_chunk}")
        ])
        
        chain = prompt | llm
        response = chain.invoke({"syllabus_chunk": syllabus_chunk})
        
        content = response.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        quiz_json = json.loads(content)
        return jsonify({"success": True, "quiz": quiz_json})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
# ADD THE TIMETABLE ROUTE RIGHT HERE:
# ==========================================
@app.route('/api/timetable', methods=['POST'])
def generate_timetable():
    if 'pdf' not in request.files:
        return jsonify({"success": False, "message": "No PDF file provided."}), 400
    
    file = request.files['pdf']
    wake_time = request.form.get('wake_time', '').strip()
    sleep_time = request.form.get('sleep_time', '').strip()
    dinner_time = request.form.get('dinner_time', '').strip()
    travel_timestamps = request.form.get('travel_timestamps', '').strip()

    if file.filename == '':
        return jsonify({"success": False, "message": "No selected file."}), 400

    filename = secure_filename(file.filename)
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(pdf_path)

    try:
        raw_text = extract_pdf_text(pdf_path)
        if not raw_text.strip():
            return jsonify({"success": False, "message": "No text could be extracted from this PDF."}), 400
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an expert AI productivity coach and scheduler. Based on the provided college/school timetable PDF and user routine constraints, "
                       "generate a comprehensive, personalized, and balanced daily routine and study schedule. Format it clearly with markdown headings and bullet points."),
            ("human", "Here is the college/school timetable extracted text:\n\n{timetable_text}\n\n"
                      "Here are my personal routine details:\n"
                      "- Waking up time: {wake_time}\n"
                      "- Sleeping time: {sleep_time}\n"
                      "- Dinner time: {dinner_time}\n"
                      "- Travel time/timestamps: {travel_timestamps}")
        ])
        
        chain = prompt | llm
        response = chain.invoke({
            "timetable_text": raw_text[:4000],
            "wake_time": wake_time or "Not specified",
            "sleep_time": sleep_time or "Not specified",
            "dinner_time": dinner_time or "Not specified",
            "travel_timestamps": travel_timestamps or "None"
        })
        
        return jsonify({"success": True, "timetable": response.content})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)