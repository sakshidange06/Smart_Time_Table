# app.py
import os
import re
import json
import uuid
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for, Response, abort, send_from_directory
)
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from pypdf import PdfReader
from langchain_core.prompts import ChatPromptTemplate

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from llm import llm
from coordinator import (
    coordinator_bp, init_user_csv, register_user, verify_user,
    start_session, end_session, current_user, student_required,
)

# =========================================================
# FLASK CONFIGURATION
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
# static_folder=None: files are NOT served automatically (see the whitelisted route below)
app = Flask(__name__, template_folder=".", static_folder=None)

# Render sits behind a proxy: trust its https/host headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.getenv("RENDER")),
    MAX_CONTENT_LENGTH=20 * 1024 * 1024,  # 20 MB upload limit
)

USER_CSV = "users.csv"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Professor login + professor timetables live in coordinator.py
app.register_blueprint(coordinator_bp)
init_user_csv()

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

ALLOWED_ASSET_EXTENSIONS = {
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".otf",
}


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    if isinstance(e, HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": e.description}), e.code
        return e
    traceback.print_exc()
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "message": f"Server error: {e}"}), 500
    return "Internal server error", 500


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
    """Save an uploaded PDF under a unique name. Returns the path, or None if it is not a PDF."""
    filename = secure_filename(file.filename or "")
    if not filename.lower().endswith(".pdf"):
        return None
    pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], f"{uuid.uuid4().hex[:8]}_{filename}")
    file.save(pdf_path)
    return pdf_path


def remove_file(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


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


def ics_escape(text):
    return (str(text).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r", "").replace("\n", "\\n"))


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
# HOME, ASSETS & STUDENT AUTH
# =========================================================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/me")
def whoami():
    role, username = current_user()
    if not role:
        return jsonify({"success": False, "role": None})
    return jsonify({"success": True, "role": role, "username": username})


@app.route("/<path:filename>")
def serve_asset(filename):
    """Only CSS, JS, images and fonts are served, so source code stays private."""
    if Path(filename).suffix.lower() not in ALLOWED_ASSET_EXTENSIONS:
        abort(404)
    return send_from_directory(BASE_DIR, filename)


# =========================================================
# STUDENT AUTHENTICATION
# =========================================================
@app.route("/api/register", methods=["POST"])
def student_register():
    data = request.json or {}
    try:
        ok, message = register_user(data.get("username", ""), data.get("password", ""), role="student")
    except PermissionError:
        return jsonify({"success": False, "message": "Cannot write users.csv. Close it if it is open in Excel and try again."}), 500
    return jsonify({"success": ok, "message": message}), (200 if ok else 400)


@app.route("/api/login", methods=["POST"])
def student_login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if verify_user(username, password, role="student"):
        start_session("student", username)
        return jsonify({"success": True, "username": username, "message": "Login successful!"})
    return jsonify({"success": False, "message": "Invalid username or password."}), 401


@app.route("/api/logout", methods=["POST"])
def student_logout():
    end_session("student")
    session.pop("google_creds", None)  # do not leave one student's Google link for the next user
    return jsonify({"success": True, "message": "Logged out."})

# =========================================================
# QUIZ GENERATOR
# =========================================================
@app.route("/api/quiz", methods=["POST"])
@student_required
def generate_quiz():
    if "pdf" not in request.files:
        return jsonify({"success": False, "message": "No PDF file provided."}), 400
    file = request.files["pdf"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No selected file."}), 400
    pdf_path = save_uploaded_pdf(file)
    if not pdf_path:
        return jsonify({"success": False, "message": "Please upload a PDF file."}), 400
    try:
        raw_text = extract_pdf_text(pdf_path)
        if not raw_text.strip():
            return jsonify({"success": False, "message": "No text could be extracted from this PDF."}), 400

        chunks = chunk_text(raw_text)
        syllabus_chunk = "\n".join(chunks[:2]) if chunks else raw_text[:3000]

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert AI tutor. Generate a 5-question multiple-choice quiz from the "
             "provided syllabus. Return ONLY valid JSON, with no markdown and no extra text.\n"
             "Format:\n"
             "[\n"
             "  {{\n"
             "    \"id\": 1,\n"
             "    \"question\": \"Question text?\",\n"
             "    \"options\": [\"A) Option 1\", \"B) Option 2\", \"C) Option 3\", \"D) Option 4\"],\n"
             "    \"answer\": \"A\"\n"
             "  }}\n"
             "]"),
            ("human", "Syllabus / notes:\n{syllabus_chunk}"),
        ])
        response = (prompt | llm).invoke({"syllabus_chunk": syllabus_chunk})
        content = response_to_text(response)

        # keep only the JSON array, even if the model added fences or text around it
        first, last = content.find("["), content.rfind("]")
        if first == -1 or last == -1:
            raise ValueError("The AI did not return a valid quiz. Please try again.")
        quiz_json = json.loads(content[first:last + 1])
        return jsonify({"success": True, "quiz": quiz_json})
    except Exception as e:
        print("QUIZ ERROR:", repr(e))
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        remove_file(pdf_path)


# =========================================================
# SMART TIMETABLE
# =========================================================
@app.route("/api/timetable", methods=["POST"])
@student_required
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
    if not pdf_path:
        return jsonify({"success": False, "message": "Please upload a PDF file."}), 400
    try:
        raw_text = extract_pdf_text(pdf_path)
        if not raw_text.strip():
            return jsonify({"success": False, "message": "No text could be extracted from this PDF."}), 400

        timetable_text = raw_text[:5000]
        prompt = ChatPromptTemplate.from_messages([
            ("system", """
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
"""),
            ("human", """
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
"""),
        ])
        response = (prompt | llm).invoke({
            "timetable_text": timetable_text,
            "wake_time": wake_time or "Not specified",
            "sleep_time": sleep_time or "Not specified",
            "dinner_time": dinner_time or "Not specified",
            "travel_timestamps": travel_timestamps or "None",
        })
        timetable = response_to_text(response)
        if not timetable:
            return jsonify({"success": False, "message": "AI returned an empty response. Please try again."}), 500
        events = parse_timetable_rows(timetable)
        return jsonify({"success": True, "timetable": timetable, "events": events_for_client(events)})
    except Exception as e:
        return jsonify({"success": False, "message": f"Timetable generation failed: {str(e)}"}), 500
    finally:
        remove_file(pdf_path)


@app.route("/api/timetable/events", methods=["POST"])
@student_required
def timetable_events():
    data = request.json or {}
    events = parse_timetable_rows(data.get("timetable", ""))
    if not events:
        return jsonify({"success": False, "message": "No timed rows found."}), 400
    return jsonify({"success": True, "events": events_for_client(events)})


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
        print("GOOGLE OAUTH ERROR:", repr(e))
        return popup_page("Could not connect Google Calendar.", False)


@app.route("/api/google/status")
def google_status():
    return jsonify({"connected": get_google_credentials() is not None})


@app.route("/api/google/disconnect", methods=["POST"])
def google_disconnect():
    session.pop("google_creds", None)
    return jsonify({"success": True})


@app.route("/api/calendar/add", methods=["POST"])
@student_required
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
@student_required
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
            f"SUMMARY:{ics_escape(ev['activity'])}",
            f"DESCRIPTION:{ics_escape(ev['purpose'])}",
        ]
        if repeat_days > 1:
            lines.append(f"RRULE:FREQ=DAILY;COUNT={repeat_days}")
        if reminder_minutes > 0:
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{ics_escape(ev['activity'])}",
                f"TRIGGER:-PT{reminder_minutes}M",
                "END:VALARM",
            ]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return Response(
        "\r\n".join(lines) + "\r\n",
        mimetype="text/calendar",
        headers={"Content-Disposition": "attachment; filename=timetable.ics"},
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)