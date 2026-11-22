# app.py
import json
import os
import re
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from langchain_core.prompts import ChatPromptTemplate
from pypdf import PdfReader
from sqlalchemy import select
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from coordinator import (
    coordinator_bp,
    current_user,
    end_session,
    register_user,
    start_session,
    student_required,
    verify_user,
)
from db import (
    ChatMessageRecord,
    ChatSessionRecord,
    TimetableRecord,
    UserRecord,
    get_db_session,
    init_db,
)
from llm import llm

# =========================================================
# FLASK CONFIGURATION
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=".", static_folder=None)

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key")
_is_render_https = (os.getenv("RENDER") or "").strip().lower() in {"1", "true", "yes"}
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_is_render_https,
    MAX_CONTENT_LENGTH=20 * 1024 * 1024,
)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

init_db()
app.register_blueprint(coordinator_bp)

# ---------------- Google Calendar settings ----------------
GOOGLE_CLIENT_SECRETS = (
    "/etc/secrets/credentials.json"
    if os.path.exists("/etc/secrets/credentials.json")
    else str(BASE_DIR / "credentials.json")
)
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
if not _is_render_https:
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
# DATABASE PERSISTENCE HELPERS (SQLAlchemy / PostgreSQL)
# =========================================================
def _resolve_active_user(db):
    role, username = current_user()
    if not username:
        return None
    user = db.execute(
        select(UserRecord).where(UserRecord.username == username.strip())
    ).scalar_one_or_none()
    if user is None:
        normalized_role = "professor" if role == "professor" else "student"
        user = UserRecord(
            username=username.strip(),
            password_hash="managed-via-auth",
            role=normalized_role,
        )
        db.add(user)
        db.flush()
    return user


def _get_or_create_user_session(db, user_id: int, session_id: str | None, default_title: str) -> ChatSessionRecord:
    clean_sid = (session_id or "").strip()
    if clean_sid:
        existing = db.execute(
            select(ChatSessionRecord).where(ChatSessionRecord.session_id == clean_sid)
        ).scalar_one_or_none()
        if existing is not None:
            existing.updated_at = datetime.now(timezone.utc)
            return existing

    new_sid = clean_sid or f"sess_{uuid.uuid4().hex[:12]}"
    rec = ChatSessionRecord(
        session_id=new_sid,
        user_id=user_id,
        title=default_title[:255],
    )
    db.add(rec)
    db.flush()
    return rec


def persist_activity_and_timetable(
    *,
    session_id: str | None,
    title: str,
    summary_text: str,
    timetable_payload: dict | None = None,
    department: str = "Student Routine",
) -> str | None:
    try:
        with get_db_session() as db:
            user = _resolve_active_user(db)
            if user is None:
                return None

            sess = _get_or_create_user_session(db, user.id, session_id, title)
            if summary_text:
                db.add(
                    ChatMessageRecord(
                        session_id=sess.id,
                        sender="assistant",
                        content=summary_text,
                        is_html=False,
                    )
                )

            if timetable_payload is not None:
                db.add(
                    TimetableRecord(
                        session_id=sess.id,
                        department=department[:120],
                        payload_json=json.dumps(timetable_payload, ensure_ascii=False),
                    )
                )

            return sess.session_id
    except Exception as exc:
        print("DB PERSIST WARNING:", repr(exc))
        return session_id


# =========================================================
# PDF / LLM HELPERS
# =========================================================
def chunk_text(text, chunk_size=1500, overlap=150):
    chunks = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(text):
        chunks.append(text[start:start + chunk_size])
        start += step
    return chunks


def sample_chunks_evenly(chunks, max_chunks=4):
    if len(chunks) <= max_chunks:
        return chunks
    step = len(chunks) / max_chunks
    indices = [min(len(chunks) - 1, int(i * step)) for i in range(max_chunks)]
    seen = set()
    sampled = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            sampled.append(chunks[idx])
    return sampled


def validate_quiz_items(raw_items):
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("The AI did not return a valid quiz list. Please try again.")
    validated = []
    for idx, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        options = item.get("options")
        answer = str(item.get("answer") or "").strip().upper()[:1]
        if not question or not isinstance(options, list) or len(options) < 2:
            continue
        clean_options = [str(opt).strip() for opt in options if str(opt).strip()][:4]
        if answer not in {"A", "B", "C", "D"}:
            answer = "A"
        validated.append({
            "id": idx,
            "question": question,
            "options": clean_options,
            "answer": answer,
        })
    if not validated:
        raise ValueError("No valid quiz questions could be parsed from AI output.")
    return validated


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
# TIMETABLE PARSER & STRICT 24-HOUR NORMALIZER
# =========================================================
TIME_RE = re.compile(r"(\d{1,2})(?:[:.](\d{2}))?\s*([AaPp]\.?\s*[Mm]\.?)?")

DAY_MAP = {
    "mon": "Monday",
    "monday": "Monday",
    "tue": "Tuesday",
    "tues": "Tuesday",
    "tuesday": "Tuesday",
    "wed": "Wednesday",
    "weds": "Wednesday",
    "wednesday": "Wednesday",
    "thu": "Thursday",
    "thur": "Thursday",
    "thurs": "Thursday",
    "thursday": "Thursday",
    "fri": "Friday",
    "friday": "Friday",
    "sat": "Saturday",
    "saturday": "Saturday",
    "sun": "Sunday",
    "sunday": "Sunday",
    "daily": "Daily",
    "all days": "Daily",
    "everyday": "Daily",
}


def normalize_day_label(raw_day, fallback="Monday"):
    cleaned = re.sub(r"\*\*|__|`", "", str(raw_day or "")).strip()
    if not cleaned:
        return fallback
    key = cleaned.lower().rstrip(".")
    return DAY_MAP.get(key, cleaned.title())


def _to_minutes(hour, minute, meridiem):
    if meridiem:
        is_pm = meridiem[0].lower() == "p"
        if hour == 12:
            hour = 12 if is_pm else 0
        else:
            hour = hour + (12 if is_pm else 0)
    return hour * 60 + minute


def _fmt_24h(minutes):
    clamped = max(0, min(int(minutes), 23 * 60 + 59))
    return f"{clamped // 60:02d}:{clamped % 60:02d}"


def parse_time_range(cell):
    matches = list(TIME_RE.finditer(cell.strip()))
    if len(matches) < 2:
        return None
    a, b = matches[0], matches[1]
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


def _coerce_24h_day_events(raw_events, sleep_time_str=""):
    """Convert raw day events into strict 24-hour non-overlapping single-day slots."""
    if not raw_events:
        return []

    default_sleep_start = 22 * 60 + 30
    if sleep_time_str:
        parsed_sleep = parse_time_range(f"{sleep_time_str} - 23:30")
        if parsed_sleep:
            default_sleep_start = max(20 * 60, min(parsed_sleep[0], 23 * 60 + 20))

    cleaned = []
    seen_evening_markers = False

    for ev in raw_events:
        start = ev["start"]
        end = ev["end"]
        activity = ev["activity"]
        cat = classify_activity(activity)

        # Fix 12-hour ambiguity after lunch (12:00+) when hour is 1..11
        if seen_evening_markers and 0 < (start // 60) < 12 and cat != "sleep":
            start += 12 * 60
        elif start >= 12 * 60 + 45 and 0 < (start // 60) < 12 and cat != "sleep":
            start += 12 * 60
            seen_evening_markers = True

        if cat in ("meal", "break") and "dinner" in activity.lower() and start < 17 * 60:
            start += 12 * 60
            seen_evening_markers = True

        if "dinner" in activity.lower() or "sleep" in activity.lower() or "wind-down" in activity.lower():
            seen_evening_markers = True

        if cat == "sleep":
            start = max(default_sleep_start, start if start >= 20 * 60 else default_sleep_start)
            end = max(start + 30, min(23 * 60 + 59, end if end > start and end < 24 * 60 else 23 * 60 + 30))
        else:
            duration = end - start
            if duration <= 0:
                duration = 30
            end = min(23 * 60 + 30, start + duration)

        cleaned.append({
            "day": ev["day"],
            "start": start,
            "end": end,
            "activity": activity,
            "purpose": ev["purpose"],
            "category": cat,
        })

    # Keep non-sleep items in order and place sleep at the end
    non_sleep = [item for item in cleaned if item["category"] != "sleep"]
    sleep_items = [item for item in cleaned if item["category"] == "sleep"]

    normalized = []
    cursor = None
    for item in non_sleep:
        dur = max(15, item["end"] - item["start"])
        s = item["start"]
        if cursor is not None and s < cursor:
            s = cursor
        s = min(s, 23 * 60)
        e = min(23 * 60 + 45, max(s + 15, s + dur))
        normalized.append({
            **item,
            "start": s,
            "end": e,
        })
        cursor = e

    for sl in sleep_items:
        s = max(cursor or default_sleep_start, default_sleep_start)
        s = min(s, 23 * 60 + 15)
        e = min(23 * 60 + 59, max(s + 30, 23 * 60 + 30))
        normalized.append({
            **sl,
            "start": s,
            "end": e,
        })
        cursor = e

    return normalized


def format_24h_timetable_markdown(events, raw_markdown=""):
    """Rebuild the timetable table strictly in 24-hour HH:MM - HH:MM format."""
    if not events:
        return raw_markdown

    lines = [
        "| Day | Time | Activity | Purpose |",
        "|-----|------|----------|---------|",
    ]
    for ev in events:
        time_str = f"{_fmt_24h(ev['start'])} - {_fmt_24h(ev['end'])}"
        purpose = ev["purpose"] or "Daily routine"
        lines.append(f"| {ev['day']} | {time_str} | {ev['activity']} | {purpose} |")

    # Append any trailing sections (Top 3 Study Priorities / Productivity Tips) if present
    extra_match = re.search(r"(###\s+Top\s+3\s+Study\s+Priorities[\s\S]*)$", raw_markdown, re.IGNORECASE)
    if extra_match:
        lines.append("")
        lines.append(extra_match.group(1).strip())

    return "\n".join(lines)


def events_for_client(events):
    return [
        {
            "day": e.get("day", "Monday"),
            "start": e["start"],
            "start_label": _fmt_24h(e["start"]),
            "end_label": _fmt_24h(e["end"]),
            "activity": e["activity"],
            "purpose": e["purpose"],
            "category": e["category"],
            "spans_midnight": False,
        }
        for e in events
    ]


def parse_timetable_rows(markdown_text, sleep_time_str=""):
    grouped_by_day = {}
    day_order = []
    current_day = "Monday"

    for line in markdown_text.splitlines():
        line = line.strip()
        if not line:
            continue
        day_heading = re.match(
            r"^#{1,4}\s*(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b",
            line,
            re.IGNORECASE,
        )
        if day_heading:
            current_day = normalize_day_label(day_heading.group(1), current_day)
            continue

        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue

        parsed_day = current_day
        time_range = parse_time_range(cells[0])
        act_idx = 1
        purp_idx = 2
        if time_range is None and len(cells) >= 3:
            maybe_range = parse_time_range(cells[1])
            if maybe_range is not None:
                parsed_day = normalize_day_label(cells[0], current_day)
                current_day = parsed_day
                time_range = maybe_range
                act_idx = 2
                purp_idx = 3

        if not time_range:
            continue

        activity = _clean(cells[act_idx]) if len(cells) > act_idx else ""
        purpose = _clean(cells[purp_idx]) if len(cells) > purp_idx else ""
        if not activity:
            continue

        if parsed_day not in grouped_by_day:
            grouped_by_day[parsed_day] = []
            day_order.append(parsed_day)

        grouped_by_day[parsed_day].append({
            "day": parsed_day,
            "start": time_range[0],
            "end": time_range[1],
            "activity": activity,
            "purpose": purpose,
            "category": classify_activity(activity),
        })

    all_events = []
    for d in day_order:
        all_events.extend(_coerce_24h_day_events(grouped_by_day[d], sleep_time_str=sleep_time_str))
    return all_events


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
    timezone_name = (data.get("timezone") or "Asia/Kolkata").strip()
    try:
        reminder_minutes = max(0, min(int(data.get("reminder_minutes", 10)), 1440))
    except (TypeError, ValueError):
        reminder_minutes = 10
    return events, day, repeat_days, timezone_name, reminder_minutes


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
        window.opener.postMessage("{status}", "*");
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
    if Path(filename).suffix.lower() not in ALLOWED_ASSET_EXTENSIONS:
        abort(404)
    return send_from_directory(BASE_DIR, filename)


# =========================================================
# STUDENT AUTHENTICATION
# =========================================================
@app.route("/api/register", methods=["POST"])
def student_register():
    data = request.json or {}
    ok, message = register_user(data.get("username", ""), data.get("password", ""), role="student")
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
    session.pop("google_creds", None)
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
        sampled_chunks = sample_chunks_evenly(chunks, max_chunks=4) if chunks else [raw_text[:3000]]
        syllabus_chunk = "\n---\n".join(sampled_chunks)[:6000]

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

        first, last = content.find("["), content.rfind("]")
        if first == -1 or last == -1:
            raise ValueError("The AI did not return a valid quiz. Please try again.")
        quiz_json = validate_quiz_items(json.loads(content[first:last + 1]))

        req_session_id = request.form.get("session_id") or (request.json.get("session_id") if request.is_json else None)
        saved_sid = persist_activity_and_timetable(
            session_id=req_session_id,
            title=f"Quiz: {secure_filename(file.filename or 'Syllabus')}",
            summary_text=f"Generated a {len(quiz_json)}-question quiz from {secure_filename(file.filename or 'PDF')}.",
        )
        return jsonify({"success": True, "quiz": quiz_json, "session_id": saved_sid})
    except Exception as e:
        print("QUIZ ERROR:", repr(e))
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        remove_file(pdf_path)


# =========================================================
# SMART TIMETABLE (STRICT 24-HOUR FORMAT, MON-SAT)
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
    req_session_id = request.form.get("session_id")

    pdf_path = save_uploaded_pdf(file)
    if not pdf_path:
        return jsonify({"success": False, "message": "Please upload a PDF file."}), 400
    try:
        raw_text = extract_pdf_text(pdf_path)
        if not raw_text.strip():
            return jsonify({"success": False, "message": "No text could be extracted from this PDF."}), 400

        if len(raw_text) <= 8000:
            timetable_text = raw_text
        else:
            sampled_tt = sample_chunks_evenly(
                chunk_text(raw_text, chunk_size=2000, overlap=100),
                max_chunks=4,
            )
            timetable_text = "\n---\n".join(sampled_tt)[:8000]

        prompt = ChatPromptTemplate.from_messages([
            ("system", """
You are an AI student timetable planner.
Generate a complete 6-day timetable (Monday through Saturday) in STRICT 24-HOUR FORMAT (00:00 to 23:59).
Never write AM/PM and never use 12-hour numbers for afternoon/evening slots (e.g., use 13:45 instead of 01:45, 18:00 instead of 06:00, 19:30 instead of 07:30, 22:30 instead of 10:30).

Rules:
1. Cover Monday, Tuesday, Wednesday, Thursday, Friday, and Saturday with Day in column 1.
2. Format every time range strictly as HH:MM - HH:MM in 24-hour time (e.g., 06:30 - 07:00, 13:00 - 14:00, 22:30 - 23:30).
3. Keep each day within a single day from wake-up to bedtime; never create a multi-hour daytime sleep block.
4. Copy college subjects/classes accurately from the PDF without inventing classes.
5. Include travel times, dinner, breakfast, lunch, breaks, study/revision, and wind-down.

Return ONLY this format:
| Day | Time | Activity | Purpose |
|-----|------|----------|---------|

### Top 3 Study Priorities
1. ...
2. ...
3. ...

### Productivity Tips
- ...
- ...
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

Generate the 6-day timetable in strict 24-hour HH:MM - HH:MM format now.
"""),
        ])
        response = (prompt | llm).invoke({
            "timetable_text": timetable_text,
            "wake_time": wake_time or "06:30",
            "sleep_time": sleep_time or "22:30",
            "dinner_time": dinner_time or "19:30",
            "travel_timestamps": travel_timestamps or "None",
        })
        raw_timetable = response_to_text(response)
        if not raw_timetable:
            return jsonify({"success": False, "message": "AI returned an empty response. Please try again."}), 500

        events = parse_timetable_rows(raw_timetable, sleep_time_str=sleep_time)
        timetable = format_24h_timetable_markdown(events, raw_markdown=raw_timetable)
        client_events = events_for_client(events)

        saved_sid = persist_activity_and_timetable(
            session_id=req_session_id,
            title=f"Timetable: {secure_filename(file.filename or 'Routine')}",
            summary_text=timetable,
            timetable_payload={
                "markdown": timetable,
                "events": client_events,
                "routine": {
                    "wake_time": wake_time,
                    "sleep_time": sleep_time,
                    "dinner_time": dinner_time,
                    "travel_timestamps": travel_timestamps,
                },
            },
            department="Student Routine",
        )
        return jsonify({
            "success": True,
            "timetable": timetable,
            "events": client_events,
            "session_id": saved_sid,
        })
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
    wants_json = (
        request.args.get("format") == "json"
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.headers.get("Accept", "").startswith("application/json")
    )
    if not os.path.exists(GOOGLE_CLIENT_SECRETS):
        msg = "Google credentials.json was not found on server. Place credentials.json in the project root or /etc/secrets/credentials.json."
        return (jsonify({"success": False, "message": msg}), 500) if wants_json else (msg, 500)
    try:
        flow = make_flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        session["google_state"] = state
        session["google_code_verifier"] = getattr(flow, "code_verifier", None)
        if wants_json:
            return jsonify({"success": True, "auth_url": auth_url})
        return redirect(auth_url)
    except Exception as e:
        print("GOOGLE LOGIN ERROR:", repr(e))
        msg = f"Could not start Google sign-in: {e}"
        return (jsonify({"success": False, "message": msg}), 500) if wants_json else (msg, 500)


@app.route("/oauth2callback")
def oauth2callback():
    if request.args.get("error"):
        return popup_page("Google sign-in was cancelled.", False)
    state = session.get("google_state")
    if not state:
        return popup_page("Session expired or cookies were blocked. Check redirect URI & HTTPS settings, then try again.", False)
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
        return popup_page(f"Could not connect Google Calendar: {e}", False)


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
    events, day, repeat_days, timezone_name, reminder_minutes = read_calendar_request()
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
            summary = f"[{ev['day']}] {ev['activity']}" if ev.get("day") and ev["day"] != "Daily" else ev["activity"]
            body = {
                "summary": summary,
                "description": ev["purpose"],
                "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": timezone_name},
                "end": {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": timezone_name},
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
    events, day, repeat_days, _timezone_name, reminder_minutes = read_calendar_request()
    if not events:
        return jsonify({"success": False, "message": "No timed rows found."}), 400
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Smart Timetable AI//EN", "CALSCALE:GREGORIAN"]
    for ev in events:
        start_dt = day + timedelta(minutes=ev["start"])
        end_dt = day + timedelta(minutes=ev["end"])
        summary = f"[{ev['day']}] {ev['activity']}" if ev.get("day") and ev["day"] != "Daily" else ev["activity"]
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uuid.uuid4()}@smart-timetable",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{ics_escape(summary)}",
            f"DESCRIPTION:{ics_escape(ev['purpose'])}",
        ]
        if repeat_days > 1:
            lines.append(f"RRULE:FREQ=DAILY;COUNT={repeat_days}")
        if reminder_minutes > 0:
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{ics_escape(summary)}",
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