import os
import re
import csv
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for, Response
)
from werkzeug.utils import secure_filename
from pypdf import PdfReader
from langchain_core.prompts import ChatPromptTemplate

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from llm import llm  # llm.py also loads the .env file


# =========================================================
# FLASK CONFIGURATION
# =========================================================

app = Flask(__name__, template_folder=".", static_folder=".")

# Needed for login sessions (Google tokens are kept in the session).
# Put FLASK_SECRET_KEY=some-long-random-text in your .env file.
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key")

USER_CSV = "users.csv"
UPLOAD_FOLDER = "uploads"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ---------------- Google Calendar settings ----------------

GOOGLE_CLIENT_SECRETS = "credentials.json"  # downloaded from Google Cloud Console
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# Local development runs on http://, so allow it.
# Remove these two lines if you deploy with https.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


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
# TIMETABLE PARSER (markdown table -> list of events)
# =========================================================

TIME_RE = re.compile(r"(\d{1,2})(?:[:.](\d{2}))?\s*([AaPp]\.?[Mm]\.?)?")
RANGE_SPLIT_RE = re.compile(r"\s*(?:[-\u2013\u2014]|\bto\b)\s*", re.IGNORECASE)


def _to_minutes(hour, minute, meridiem):
    if meridiem:
        is_pm = meridiem[0].lower() == "p"
        hour = hour % 12 + (12 if is_pm else 0)
    return hour * 60 + minute


def parse_time_range(cell):
    """'06:00 - 06:30', '6:00 AM – 7:15 AM', '6:00-6:30 AM' -> (start_min, end_min)"""
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
        # "6:00 - 6:30 AM": start shares the end's AM/PM unless that makes it later
        end = _to_minutes(hb, mb, merb)
        start = _to_minutes(ha, ma, merb)
        if start > end:
            other = "a" if merb[0].lower() == "p" else "p"
            start = _to_minutes(ha, ma, other)
    else:
        start = _to_minutes(ha, ma, mera)
        end = _to_minutes(hb, mb, merb)

    if end <= start:
        end += 24 * 60  # crosses midnight (for example, sleep)

    return start, end


def _clean(text):
    return re.sub(r"\*\*|__|`", "", text).strip()


def classify_activity(activity):
    """Guess what kind of activity a row is, so reminders can be friendly."""
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
    """Shape the parsed events for the browser notification scheduler."""
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

        # Skip the |-----|-----| separator row
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue

        time_range = parse_time_range(cells[0])
        if not time_range:
            continue  # header row or a row without a time

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
    """Reminder times in minutes before the event. Always includes 'at start'
    (for example 10 -> [10, 0]: a notification 10 minutes before and at the start)."""
    return [0] if minutes == 0 else [minutes, 0]


def read_calendar_request():
    """Read and validate the JSON sent by the browser."""
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

    # How many minutes BEFORE each activity the notification should appear.
    # A second notification always appears exactly at the start time.
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
    """Small page shown in the login popup. It tells the main page and closes."""
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
14. Write every time as a range like
    06:00 - 06:30 (24-hour format).

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

        events = parse_timetable_rows(timetable)

        return jsonify({
            "success": True,
            "timetable": timetable,
            "events": events_for_client(events),
        })

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
# GOOGLE CALENDAR: CONNECT
# =========================================================

@app.route("/google/login")
def google_login():
    if not os.path.exists(GOOGLE_CLIENT_SECRETS):
        return (
            "credentials.json was not found. Download it from Google Cloud "
            "Console and place it next to app.py.",
            500,
        )

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


# =========================================================
# GOOGLE CALENDAR: ADD EVENTS
# =========================================================

@app.route("/api/calendar/add", methods=["POST"])
def add_to_google_calendar():
    events, day, repeat_days, timezone, reminder_minutes = read_calendar_request()

    if not events:
        return jsonify({
            "success": False,
            "message": "No timed rows were found in the timetable."
        }), 400

    creds = get_google_credentials()
    if not creds:
        return jsonify({
            "success": False,
            "needs_auth": True,
            "message": "Please connect your Google account first."
        }), 401

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
                # Notifications on phone / desktop Google Calendar
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "popup", "minutes": m} for m in reminder_offsets
                    ],
                },
            }

            if repeat_days > 1:
                body["recurrence"] = [f"RRULE:FREQ=DAILY;COUNT={repeat_days}"]

            service.events().insert(calendarId="primary", body=body).execute()
            created += 1

        return jsonify({
            "success": True,
            "created": created,
            "link": f"https://calendar.google.com/calendar/u/0/r/day/{day.year}/{day.month}/{day.day}",
        })

    except HttpError as e:
        print("GOOGLE CALENDAR API ERROR:", repr(e))
        return jsonify({
            "success": False,
            "message": f"Google Calendar error: {e.reason if hasattr(e, 'reason') else e}"
        }), 500

    except Exception as e:
        print("CALENDAR ERROR:", repr(e))
        return jsonify({"success": False, "message": str(e)}), 500


# =========================================================
# CALENDAR FILE (.ics) - works without any Google setup
# =========================================================

def _ics_escape(text):
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


@app.route("/api/calendar/ics", methods=["POST"])
def download_ics():
    events, day, repeat_days, _timezone, reminder_minutes = read_calendar_request()

    if not events:
        return jsonify({
            "success": False,
            "message": "No timed rows were found in the timetable."
        }), 400

    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Smart Timetable AI//EN",
        "CALSCALE:GREGORIAN",
    ]

    for ev in events:
        start_dt = day + timedelta(minutes=ev["start"])
        end_dt = day + timedelta(minutes=ev["end"])

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uuid.uuid4()}@smart-timetable",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{_ics_escape(ev['activity'])}",
            f"DESCRIPTION:{_ics_escape(ev['purpose'])}",
        ]
        if repeat_days > 1:
            lines.append(f"RRULE:FREQ=DAILY;COUNT={repeat_days}")

        for m in build_reminder_offsets(reminder_minutes):
            trigger = "PT0S" if m == 0 else f"-PT{m}M"
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_ics_escape(ev['activity'])}",
                f"TRIGGER:{trigger}",
                "END:VALARM",
            ]

        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    return Response(
        "\r\n".join(lines) + "\r\n",
        mimetype="text/calendar",
        headers={"Content-Disposition": "attachment; filename=timetable.ics"},
    )


# =========================================================
# EVENTS FOR BROWSER NOTIFICATIONS
# =========================================================

@app.route("/api/timetable/events", methods=["POST"])
def timetable_events():
    """Return each timed row (start time, activity, category) so the page
    can show a notification at wake-up, study, meal and sleep times."""
    data = request.json or {}
    events = parse_timetable_rows(data.get("timetable", ""))

    if not events:
        return jsonify({
            "success": False,
            "message": "No timed rows were found in the timetable."
        }), 400

    return jsonify({"success": True, "events": events_for_client(events)})


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":
    app.run(debug=True, port=5000)