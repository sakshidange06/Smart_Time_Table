import os
import csv
import json
from pathlib import Path

from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
from pypdf import PdfReader
from langchain_core.prompts import ChatPromptTemplate

from llm import llm


# =========================================================
# FLASK CONFIGURATION
# =========================================================

app = Flask(__name__, template_folder=".", static_folder=".")

USER_CSV = "users.csv"
UPLOAD_FOLDER = "uploads"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# =========================================================
# USER MANAGEMENT
# =========================================================

def init_user_csv():
    if not os.path.exists(USER_CSV):
        with open(USER_CSV, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["username", "password"])
            writer.writerow(["admin", "password123"])


init_user_csv()


def verify_credentials(username, password):
    if not os.path.exists(USER_CSV):
        init_user_csv()

    with open(USER_CSV, mode="r", newline="") as f:
        for row in csv.DictReader(f):
            if row["username"] == username and row["password"] == password:
                return True
    return False


def register_new_user(username, password):
    if not os.path.exists(USER_CSV):
        init_user_csv()

    with open(USER_CSV, mode="r", newline="") as f:
        for row in csv.DictReader(f):
            if row["username"] == username:
                return False, "Username already exists. Please choose another."

    with open(USER_CSV, mode="a", newline="") as f:
        csv.writer(f).writerow([username, password])

    return True, "Registration successful!"


# =========================================================
# PDF / LLM HELPERS
# =========================================================

def chunk_text(text, chunk_size=1500, overlap=150):
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start:start + chunk_size])
        start += chunk_size - overlap
    return chunks


def extract_pdf_text(pdf_path):
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


def response_to_text(response):
    """Safely turn a LangChain response into a plain string."""
    if response is None:
        return ""

    content = getattr(response, "content", "")

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        content = "\n".join(parts)

    return str(content or "").strip()


def save_uploaded_pdf(file):
    filename = secure_filename(file.filename)
    pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(pdf_path)
    return pdf_path


# =========================================================
# HOME
# =========================================================

@app.route("/")
def index():
    return render_template("index.html")


# =========================================================
# LOGIN
# =========================================================

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if verify_credentials(username, password):
        return jsonify({"success": True, "message": "Login successful!"})

    return jsonify({
        "success": False,
        "message": "Invalid username or password."
    }), 401


# =========================================================
# REGISTER
# =========================================================

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({
            "success": False,
            "message": "Username and password cannot be empty."
        }), 400

    success, message = register_new_user(username, password)

    if success:
        return jsonify({"success": True, "message": message})

    return jsonify({"success": False, "message": message}), 400


# =========================================================
# QUIZ GENERATOR
# =========================================================

@app.route("/api/quiz", methods=["POST"])
def generate_quiz():
    if "pdf" not in request.files:
        return jsonify({"success": False, "message": "No PDF file provided."}), 400

    file = request.files["pdf"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No selected file."}), 400

    pdf_path = save_uploaded_pdf(file)

    try:
        raw_text = extract_pdf_text(pdf_path)

        if not raw_text.strip():
            return jsonify({
                "success": False,
                "message": "No text could be extracted from this PDF."
            }), 400

        chunks = chunk_text(raw_text)
        syllabus_chunk = chunks[0] if chunks else raw_text[:1500]

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                """
You are an expert AI tutor.

Generate a structured
5-question multiple-choice quiz
from the provided syllabus.

Return ONLY valid JSON.

Do not use markdown.

Format:

[
  {{
    "id": 1,
    "question": "Question text?",
    "options": [
      "A) Option 1",
      "B) Option 2",
      "C) Option 3",
      "D) Option 4"
    ],
    "answer": "A"
  }}
]
"""
            ),
            (
                "human",
                """
Syllabus / notes:

{syllabus_chunk}
"""
            ),
        ])

        chain = prompt | llm
        response = chain.invoke({"syllabus_chunk": syllabus_chunk})

        content = response_to_text(response)

        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        quiz_json = json.loads(content)

        return jsonify({"success": True, "quiz": quiz_json})

    except Exception as e:
        print("QUIZ ERROR:", repr(e))
        return jsonify({"success": False, "message": str(e)}), 500


# =========================================================
# SMART TIMETABLE
# =========================================================

@app.route("/api/timetable", methods=["POST"])
def generate_timetable():
    print("\n==============================")
    print("TIMETABLE REQUEST RECEIVED")
    print("==============================")

    if "pdf" not in request.files:
        return jsonify({"success": False, "message": "No PDF file provided."}), 400

    file = request.files["pdf"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No selected file."}), 400

    wake_time = request.form.get("wake_time", "").strip()
    sleep_time = request.form.get("sleep_time", "").strip()
    dinner_time = request.form.get("dinner_time", "").strip()
    travel_timestamps = request.form.get("travel_timestamps", "").strip()

    print("Wake time:", wake_time)
    print("Sleep time:", sleep_time)
    print("Dinner time:", dinner_time)
    print("Travel:", travel_timestamps)

    pdf_path = save_uploaded_pdf(file)
    print("PDF saved:", pdf_path)

    try:
        raw_text = extract_pdf_text(pdf_path)

        if not raw_text.strip():
            return jsonify({
                "success": False,
                "message": "No text could be extracted from this PDF."
            }), 400

        print("Characters extracted:", len(raw_text))

        # Keep PDF text limited so the AI has enough completion budget.
        timetable_text = raw_text[:5000]

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                """
You are an AI student timetable planner.

Create a realistic daily timetable using
the college timetable and student routine.

Rules:

1. Start at the given wake-up time.
2. Finish before the given sleep time.
3. Copy college classes exactly from the PDF.
4. Never invent college classes.
5. Never overlap college, travel, meals,
    study, breaks or sleep.
6. Include all provided travel times.
7. Include dinner at the given time.
8. Add breakfast and lunch.
9. Add short breaks.
10. Use free time for self-study,
    revision and assignments.
11. Give priority to difficult subjects.
12. Keep some personal/relaxation time.
13. Protect sleep time.

Return ONLY this format:

| Time | Activity | Purpose |
|------|----------|---------|

### Top 3 Study Priorities

1. ...
2. ...
3. ...

### Productivity Tips

- ...
- ...
- ...

Use only information from the PDF
and student routine.
"""
            ),
            (
                "human",
                """
COLLEGE TIMETABLE:

{timetable_text}

STUDENT ROUTINE:

Wake-up:
{wake_time}

Sleep:
{sleep_time}

Dinner:
{dinner_time}

Travel:
{travel_timestamps}

Generate the timetable now.
"""
            ),
        ])

        print("TIMETABLE AI REQUEST STARTED")

        chain = prompt | llm
        response = chain.invoke({
            "timetable_text": timetable_text,
            "wake_time": wake_time or "Not specified",
            "sleep_time": sleep_time or "Not specified",
            "dinner_time": dinner_time or "Not specified",
            "travel_timestamps": travel_timestamps or "None",
        })

        print("TIMETABLE AI RESPONSE RECEIVED")

        timetable = response_to_text(response)

        if not timetable:
            print("ERROR: AI returned empty content.")
            print("Response metadata:", getattr(response, "response_metadata", None))
            return jsonify({
                "success": False,
                "message": "AI returned an empty response. Please try again."
            }), 500

        print("TIMETABLE GENERATED SUCCESSFULLY, length:", len(timetable))

        return jsonify({"success": True, "timetable": timetable})

    except Exception as e:
        print("\n==============================")
        print("TIMETABLE ERROR")
        print("==============================")
        print(repr(e))
        return jsonify({
            "success": False,
            "message": f"Timetable generation failed: {str(e)}"
        }), 500


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":
    app.run(debug=True, port=5000)