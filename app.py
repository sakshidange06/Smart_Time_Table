import os
import re
import csv
import json
import uuid
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
          Flask, request, jsonify, render_template,
          session, redirect, url_for, Response
)
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from pypdf import PdfReader
from langchain_core.prompts import ChatPromptTemplate

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from llm import llm     
from coordinator import coordinator_bp

# =========================================================
# FLASK CONFIGURATION
# =========================================================
app = Flask(__name__, template_folder=".", static_folder=".")

# Render sits behind a proxy: trust its https/host headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Needed for login sessions (Google tokens are kept in the session).
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key")

USER_CSV = "users.csv"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Register coordinator blueprint for professor services
app.register_blueprint(coordinator_bp)

# ---------------- Google Calendar settings ----------------
GOOGLE_CLIENT_SECRETS = (
          "/etc/secrets/credentials.json"
          if os.path.exists("/etc/secrets/credentials.json")
          else "credentials.json"
)
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
if not os.getenv("RENDER"):
          os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

@app.errorhandler(Exception)
def handle_unexpected_error(e):
          from werkzeug.exceptions import HTTPException
          if isinstance(e, HTTPException):
                    return e
          traceback.print_exc()
          if request.path.startswith("/api/"):
                    return jsonify({
                              "success": False,
                              "message": f"Server error: {e}"
                    }), 500
          return "Internal server error", 500

# =========================================================
# USER MANAGEMENT
# =========================================================
def init_user_csv():
    if not os.path.exists(USER_CSV) or os.path.getsize(USER_CSV) == 0:
        with open(USER_CSV, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["username", "password", "role"])
            writer.writerow(["admin", "password123", "student"])
        return

    with open(USER_CSV, mode="r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if rows and len(rows[0]) >= 2 and rows[0][0].strip().lower() == "username" and rows[0][1].strip().lower() == "password" and (len(rows[0]) < 3 or rows[0][2].strip().lower() != "role"):
        rows[0] = ["username", "password", "role"]
        for row in rows[1:]:
            if len(row) < 3:
                row.append("student")
        with open(USER_CSV, mode="w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)

def read_user_records():
    init_user_csv()
    records = []
    with open(USER_CSV, mode="r", newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            username, password = row[0].strip(), row[1].strip()
            if username.lower() == "username" and password.lower() == "password":
                continue
            role = row[2].strip().lower() if len(row) > 2 and row[2].strip() else "student"
            records.append({"username": username, "password": password, "role": role})
    return records

def verify_credentials(username, password):
    return any(
        r["username"] == username and r["password"] == password and r["role"] != "professor"
        for r in read_user_records()
    )

def verify_professor_credentials(username, password):
    return any(
        r["username"] == username and r["password"] == password and r["role"] == "professor"
        for r in read_user_records()
    )

def register_new_user(username, password, role="student"):
    if any(r["username"] == username for r in read_user_records()):
        return False, "Username already exists. Please choose another."

    needs_newline = False
    with open(USER_CSV, mode="rb") as f:
        data = f.read()
        if data and not data.endswith((b"\n", b"\r")):
            needs_newline = True

    with open(USER_CSV, mode="a", newline="", encoding="utf-8") as f:
        if needs_newline:
            f.write("\r\n")
        csv.writer(f).writerow([username, password, role])

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
# TIMETABLE PARSER & HELPERS
# =========================================================
TIME_RE = re.compile(r"(\d{1,2})(?:[:.](\d{2}))?\s*([AaPp]\.?\s*[Mm]\.?)?")
RANGE_SPLIT_RE = re.compile(r"\s*(?:[-\u2013\u2014]|\bto\b)\s*", re.IGNORECASE)

def _to_minutes(hour, minute, meridiem):
          if meridiem:
                    is_pm = meridiem[0].lower() == "p"
                    hour = hour % 12 + (12 if is_pm else 0)
          return hour * 60 + minute

def parse_time_range(cell):
          parts = RANGE_SPLIT_RE.split(cell.strip(), maxsplit=1)
          if len(parts) != 2:
                    return None
          a = TIME_RE.search(parts[0])
          b = TIME_RE.search(parts[1])
          if not a or not b:
                    return None
          ha, ma, mera = int(a.group(1)), int(a.group(2) or 0), a.group(3)
          hb, mb, merb = int(b.group(1)), int(b.group(2) or 0), b.group(3)
          if ha > 24 or hb > 24 or ma > 59 or mb > 59:
                    return None
          if mera is None and merb:
                    end = _to_minutes(hb, mb, merb)
                    start = _to_minutes(ha, ma, merb)
                    if start > end:
                              other = "a" if merb[0].lower() == "p" else "p"
                              start = _to_minutes(ha, ma, other)
          else:
                    start = _to_minutes(ha, ma, mera)
                    end = _to_minutes(hb, mb, merb)
          if end <= start:
                    end += 24 * 60
          return start, end

def _clean(text):
          return re.sub(r"\*\*|__|`", "", text).strip()

def classify_activity(activity):
          a = activity.lower()
          if any(w in a for w in ("wake", "get up")):
                    return "wake"
          if any(w in a for w in ("sleep", "bedtime", "go to bed")):
                    return "sleep"
          if any(w in a for w in ("breakfast", "lunch", "dinner", "snack", "meal")):
                    return "meal"
          if "break" in a:
                    return "break"
          if any(w in a for w in ("study", "revision", "revise", "assignment", "homework")):
                    return "study"
          if any(w in a for w in ("travel", "commute", "bus", "train")):
                    return "travel"
          return "other"

def events_for_client(events):
          def label(minutes):
                    minutes %= 24 * 60
                    return f"{minutes // 60:02d}:{minutes % 60:02d}"
          return [
                    {
                              "start": e["start"] % (24 * 60),
                              "start_label": label(e["start"]),
                              "end_label": label(e["end"]),
                              "activity": e["activity"],
                              "purpose": e["purpose"],
                              "category": e["category"],
                    }
                    for e in events
          ]

def parse_timetable_rows(markdown_text):
          events = []
          for line in markdown_text.splitlines():
                    line = line.strip()
                    if not line.startswith("|"):
                              continue
                    cells = [c.strip() for c in line.strip("|").split("|")]
                    if len(cells) < 2:
                              continue
                    if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                              continue
                    time_range = parse_time_range(cells[0])
                    if not time_range:
                              continue
                    activity = _clean(cells[1])
                    purpose = _clean(cells[2]) if len(cells) > 2 else ""
                    if not activity:
                              continue
                    events.append({
                              "start": time_range[0],
                              "end": time_range[1],
                              "activity": activity,
                              "purpose": purpose,
                              "category": classify_activity(activity),
                    })
          return events

def build_reminder_offsets(minutes):
          return [0] if minutes == 0 else [minutes, 0]

def read_calendar_request():
          data = request.json or {}
          events = parse_timetable_rows(data.get("timetable", ""))
          try:
                    day = datetime.strptime(data.get("date", ""), "%Y-%m-%d")
          except ValueError:
                    day = datetime.combine(datetime.today().date(), datetime.min.time())
          try:
                    repeat_days = max(1, min(int(data.get("repeat_days", 1)), 365))
          except (TypeError, ValueError):
                    repeat_days = 1
          timezone = (data.get("timezone") or "UTC").strip()
          try:
                    reminder_minutes = max(0, min(int(data.get("reminder_minutes", 10)), 1440))
          except (TypeError, ValueError):
                    reminder_minutes = 10
          return events, day, repeat_days, timezone, reminder_minutes

# =========================================================
# GOOGLE CALENDAR HELPERS
# =========================================================
def make_flow(state=None):
          return Flow.from_client_secrets_file(
                    GOOGLE_CLIENT_SECRETS,
                    scopes=GOOGLE_SCOPES,
                    state=state,
                    redirect_uri=url_for("oauth2callback", _external=True),
          )

def get_google_credentials():
          raw = session.get("google_creds")
          if not raw:
                    return None
          try:
                    creds = Credentials.from_authorized_user_info(json.loads(raw), GOOGLE_SCOPES)
                    if creds.expired and creds.refresh_token:
                              creds.refresh(GoogleRequest())
                              session["google_creds"] = creds.to_json()
                    return creds if creds.valid else None
          except Exception as e:
                    print("GOOGLE CREDENTIAL ERROR:", repr(e))
                    session.pop("google_creds", None)
                    return None

def popup_page(message, ok):
          status = "google-connected" if ok else "google-failed"
          return f"""<!DOCTYPE html>
<html><body style="font-family: sans-serif; text-align: center; padding: 40px;">
<h3>{message}</h3>
<p>You can close this window.</p>
<script>
     if (window.opener) {{
          window.opener.postMessage("{status}", window.location.origin);
     }}
     setTimeout(function () {{ window.close(); }}, 1200);
</script>
</body></html>"""

# =========================================================
# HOME & AUTH ROUTES
# =========================================================
@app.route("/")
def index():
          return render_template("index.html")

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
          try:
                    success, message = register_new_user(username, password)
          except PermissionError:
                    return jsonify({
                              "success": False,
                              "message": "Cannot write users.csv. Close it if it is open in Excel and try again."
                    }), 500
          if success:
                    return jsonify({"success": True, "message": message})
          return jsonify({"success": False, "message": message}), 400

# =========================================================
# PROFESSOR AUTHENTICATION 
# =========================================================
@app.route("/api/professor/register", methods=["POST"])
def professor_register():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        return jsonify({"success": False, "message": "Username and password cannot be empty."}), 400
    if len(password) < 6:
        return jsonify({"success": False, "message": "Use a password with at least 6 characters."}), 400
    try:
        success, message = register_new_user(username, password, role="professor")
    except PermissionError:
        return jsonify({"success": False, "message": "Cannot write users.csv. Close it if it is open in Excel and try again."}), 500
    return jsonify({"success": success, "message": message}), (200 if success else 400)

@app.route("/api/professor/login", methods=["POST"])
def professor_login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if verify_professor_credentials(username, password):
        session["professor_username"] = username
        session["user_role"] = "professor"
        return jsonify({"success": True, "username": username, "message": "Professor login successful."})
    return jsonify({"success": False, "message": "Invalid professor username or password."}), 401

@app.route("/api/professor/logout", methods=["POST"])
def professor_logout():
    session.pop("professor_username", None)
    session.pop("user_role", None)
    return jsonify({"success": True, "message": "Professor logged out."})

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
                         """You are an expert AI tutor.Generate a structured 5-question multiple-choice quiz from the provided syllabus.Return ONLY valid JSON.Do not use markdown.
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
                    """  ), (
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
          if "pdf" not in request.files:
                    return jsonify({"success": False, "message": "No PDF file provided."}), 400
          file = request.files["pdf"]
          if file.filename == "":
                    return jsonify({"success": False, "message": "No selected file."}), 400
          wake_time = request.form.get("wake_time", "").strip()
          sleep_time = request.form.get("sleep_time", "").strip()
          dinner_time = request.form.get("dinner_time", "").strip()
          travel_timestamps = request.form.get("travel_timestamps", "").strip()
          pdf_path = save_uploaded_pdf(file)
          try:
                    raw_text = extract_pdf_text(pdf_path)
                    if not raw_text.strip():
                              return jsonify({
                                        "success": False,
                                        "message": "No text could be extracted from this PDF."
                              }), 400
                    timetable_text = raw_text[:5000]
                    prompt = ChatPromptTemplate.from_messages([
                              (
                                        "system",
                                        """
You are an AI student timetable planner.
Create a realistic daily timetable using the college timetable and student routine.
Rules:
1. Start at the given wake-up time.
2. Finish before the given sleep time.
3. Copy college classes exactly from the PDF.
4. Never invent college classes.
5. Never overlap college, travel, meals, study, breaks or sleep.
6. Include all provided travel times.
7. Include dinner at the given time.
8. Add breakfast and lunch.
9. Add short breaks.
10. Use free time for self-study, revision and assignments.
11. Give priority to difficult subjects.
12. Keep some personal/relaxation time.
13. Protect sleep time.
14. Write every time as a range like 06:00 - 06:30 (24-hour format).

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

Use only information from the PDF and student routine.
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
                    chain = prompt | llm
                    response = chain.invoke({
                              "timetable_text": timetable_text,
                              "wake_time": wake_time or "Not specified",
                              "sleep_time": sleep_time or "Not specified",
                              "dinner_time": dinner_time or "Not specified",
                              "travel_timestamps": travel_timestamps or "None",
                    })
                    timetable = response_to_text(response)
                    if not timetable:
                              return jsonify({
                                        "success": False,
                                        "message": "AI returned an empty response. Please try again."
                              }), 500
                    events = parse_timetable_rows(timetable)
                    return jsonify({
                              "success": True,
                              "timetable": timetable,
                              "events": events_for_client(events),
                    })
          except Exception as e:
                    return jsonify({
                              "success": False,
                              "message": f"Timetable generation failed: {str(e)}"
                    }), 500

# =========================================================
# GOOGLE CALENDAR & ICS ROUTES
# =========================================================
@app.route("/google/login")
def google_login():
          if not os.path.exists(GOOGLE_CLIENT_SECRETS):
                    return "credentials.json was not found.", 500
          flow = make_flow()
          auth_url, state = flow.authorization_url(
                    access_type="offline",
                    include_granted_scopes="true",
                    prompt="consent",
          )
          session["google_state"] = state
          session["google_code_verifier"] = getattr(flow, "code_verifier", None)
          return redirect(auth_url)

@app.route("/oauth2callback")
def oauth2callback():
          if request.args.get("error"):
                    return popup_page("Google sign-in was cancelled.", False)
          state = session.get("google_state")
          if not state:
                    return popup_page("Session expired. Please try connecting again.", False)
          try:
                    flow = make_flow(state=state)
                    verifier = session.get("google_code_verifier")
                    if verifier:
                              flow.code_verifier = verifier
                    flow.fetch_token(authorization_response=request.url)
                    session["google_creds"] = flow.credentials.to_json()
                    return popup_page("Google Calendar connected!", True)
          except Exception as e:
                    return popup_page("Could not connect Google Calendar.", False)

@app.route("/api/google/status")
def google_status():
          return jsonify({"connected": get_google_credentials() is not None})

@app.route("/api/google/disconnect", methods=["POST"])
def google_disconnect():
          session.pop("google_creds", None)
          return jsonify({"success": True})

@app.route("/api/calendar/add", methods=["POST"])
def add_to_google_calendar():
          events, day, repeat_days, timezone, reminder_minutes = read_calendar_request()
          if not events:
                    return jsonify({"success": False, "message": "No timed rows found."}), 400
          creds = get_google_credentials()
          if not creds:
                    return jsonify({"success": False, "needs_auth": True, "message": "Please connect Google account."}), 401
          try:
                    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
                    reminder_offsets = build_reminder_offsets(reminder_minutes)
                    created = 0
                    for ev in events:
                              start_dt = day + timedelta(minutes=ev["start"])
                              end_dt = day + timedelta(minutes=ev["end"])
                              body = {
                                        "summary": ev["activity"],
                                        "description": ev["purpose"],
                                        "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": timezone},
                                        "end": {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": timezone},
                                        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": m} for m in reminder_offsets]},
                              }
                              if repeat_days > 1:
                                        body["recurrence"] = [f"RRULE:FREQ=DAILY;COUNT={repeat_days}"]
                              service.events().insert(calendarId="primary", body=body).execute()
                              created += 1
                    return jsonify({"success": True, "created": created})
          except Exception as e:
                    return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/calendar/ics", methods=["POST"])
def download_ics():
          events, day, repeat_days, _timezone, reminder_minutes = read_calendar_request()
          if not events:
                    return jsonify({"success": False, "message": "No timed rows found."}), 400
          stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
          lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Smart Timetable AI//EN", "CALSCALE:GREGORIAN"]
          for ev in events:
                    start_dt = day + timedelta(minutes=ev["start"])
                    end_dt = day + timedelta(minutes=ev["end"])
                    lines += [
                              "BEGIN:VEVENT",
                              f"UID:{uuid.uuid4()}@smart-timetable",
                              f"DTSTAMP:{stamp}",
                              f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}",
                              f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}",
                              f"SUMMARY:{ev['activity']}",
                              f"DESCRIPTION:{ev['purpose']}",
                    ]
                    if repeat_days > 1:
                              lines.append(f"RRULE:FREQ=DAILY;COUNT={repeat_days}")
                    lines.append("END:VEVENT")
          lines.append("END:VCALENDAR")
          return Response("\r\n".join(lines) + "\r\n", mimetype="text/calendar", headers={"Content-Disposition": "attachment; filename=timetable.ics"})

@app.route("/api/timetable/events", methods=["POST"])
def timetable_events():
          data = request.json or {}
          events = parse_timetable_rows(data.get("timetable", ""))
          if not events:
                    return jsonify({"success": False, "message": "No timed rows found."}), 400
          return jsonify({"success": True, "events": events_for_client(events)})

if __name__ == "__main__":
          app.run(debug=True, port=5000)