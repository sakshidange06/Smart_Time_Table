# coordinator.py
# Professor login + professor services (class-teacher and department timetables).
# Also holds the shared user store (users.csv) that app.py uses for student login.
import csv
import json
import os
import threading
import uuid
from datetime import datetime
from functools import wraps

from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash

coordinator_bp = Blueprint("coordinator", __name__)


# ===============================================================
# USER STORE (users.csv), PASSWORD HASHING AND SESSION HELPERS
# Shared with app.py, which uses them for the student login.
# ===============================================================
USER_CSV = "users.csv"
MIN_PASSWORD_LENGTH = 6
_HASH_PREFIXES = ("pbkdf2:", "scrypt:")
_lock = threading.RLock()  # re-entrant: register_user and verify_user call read_user_records while holding it


# ---------------------------------------------------------------
# users.csv helpers
# ---------------------------------------------------------------
def _is_hashed(value):
    return value.startswith(_HASH_PREFIXES)


def _write_records(records):
    with open(USER_CSV, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["username", "password", "role"])
        for r in records:
            writer.writerow([r["username"], r["password"], r["role"]])


def init_user_csv():
    """Create users.csv with a default admin student account if it is missing or empty."""
    with _lock:
        if os.path.exists(USER_CSV) and os.path.getsize(USER_CSV) > 0:
            return
        admin_password = os.getenv("ADMIN_PASSWORD", "password123")
        _write_records([{
            "username": "admin",
            "password": generate_password_hash(admin_password),
            "role": "student",
        }])


def read_user_records():
    init_user_csv()
    records = []
    with open(USER_CSV, mode="r", newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            username, password = row[0].strip(), row[1].strip()
            if username.lower() == "username" and password.lower() == "password":
                continue  # header row
            role = row[2].strip().lower() if len(row) > 2 and row[2].strip() else "student"
            records.append({"username": username, "password": password, "role": role})
    return records


def _role_matches(record_role, wanted_role):
    # anything that is not "professor" counts as a student account
    return (record_role == "professor") == (wanted_role == "professor")


# ---------------------------------------------------------------
# Register / verify
# ---------------------------------------------------------------
def register_user(username, password, role):
    """Create an account. Returns (ok, message)."""
    username, password = username.strip(), password.strip()
    if not username or not password:
        return False, "Username and password cannot be empty."
    if len(username) < 3 or any(ch in username for ch in ",\r\n"):
        return False, "Username must be at least 3 characters and cannot contain commas."
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Use a password with at least {MIN_PASSWORD_LENGTH} characters."

    with _lock:
        records = read_user_records()
        if any(r["username"] == username for r in records):
            return False, "Username already exists. Please choose another."
        records.append({
            "username": username,
            "password": generate_password_hash(password),
            "role": role,
        })
        _write_records(records)
    return True, "Registration successful!"


def verify_user(username, password, role):
    """Check a login for the given role ("student" or "professor").

    Old plain-text passwords still work once and are upgraded to a hash.
    """
    username, password = username.strip(), password.strip()
    with _lock:
        records = read_user_records()
        for r in records:
            if r["username"] != username or not _role_matches(r["role"], role):
                continue
            stored = r["password"]
            if _is_hashed(stored):
                return check_password_hash(stored, password)
            if stored == password:  # legacy plain-text account: upgrade it now
                r["password"] = generate_password_hash(password)
                _write_records(records)
                return True
            return False
    return False


# ---------------------------------------------------------------
# Session helpers and route guards
# ---------------------------------------------------------------
def start_session(role, username):
    """Log a user in. Only one role is active per browser at a time."""
    session.pop("student_username", None)
    session.pop("professor_username", None)
    session["user_role"] = role
    session[f"{role}_username"] = username


def end_session(role):
    session.pop(f"{role}_username", None)
    if session.get("user_role") == role:
        session.pop("user_role", None)


def current_user():
    """Return (role, username) of the logged-in user, or (None, None)."""
    role = session.get("user_role")
    if role in ("student", "professor"):
        username = session.get(f"{role}_username")
        if username:
            return role, username
    return None, None


def _login_required(role, message):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            current_role, _ = current_user()
            if current_role != role:
                return jsonify({"success": False, "message": message}), 401
            return view(*args, **kwargs)
        return wrapper
    return decorator


student_required = _login_required("student", "Please log in as a student first.")
professor_required = _login_required("professor", "Please log in as a professor first.")


# ===============================================================
# PROFESSOR LOGIN
# ===============================================================
@coordinator_bp.route("/api/professor/register", methods=["POST"])
def professor_register():
    data = request.json or {}
    try:
        ok, message = register_user(data.get("username", ""), data.get("password", ""), role="professor")
    except PermissionError:
        return jsonify({"success": False, "message": "Cannot write users.csv. Close it if it is open in Excel and try again."}), 500
    return jsonify({"success": ok, "message": message}), (200 if ok else 400)


@coordinator_bp.route("/api/professor/login", methods=["POST"])
def professor_login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if verify_user(username, password, role="professor"):
        start_session("professor", username)
        return jsonify({"success": True, "username": username, "message": "Professor login successful."})
    return jsonify({"success": False, "message": "Invalid professor username or password."}), 401


@coordinator_bp.route("/api/professor/logout", methods=["POST"])
def professor_logout():
    end_session("professor")
    return jsonify({"success": True, "message": "Professor logged out."})

HISTORY_FILE = "department_history.json"
DEFAULT_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


# ---------------------------------------------------------------
# Department history (kept in memory and mirrored to a JSON file)
# ---------------------------------------------------------------
def _load_history():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f)
    except OSError as e:
        print("HISTORY SAVE ERROR:", repr(e))


DEPARTMENT_DATABASE = {"history": _load_history()}


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------
def _parse_hhmm(hhmm_str):
    parts = str(hhmm_str).strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return hour * 60 + minute


def _fmt_hhmm(total_mins):
    total_mins %= 24 * 60
    return f"{total_mins // 60:02d}:{total_mins % 60:02d}"


def _error(message, code=400):
    return jsonify({"success": False, "message": message}), code


def _professor_error(need_at_symbol=False):
    """Return an error response if the caller is not an allowed professor, else None."""
    username = session.get("professor_username", "")
    if session.get("user_role") != "professor" or not username:
        return _error("Please log in as a professor first.", 401)
    if need_at_symbol and "@" not in username:
        return _error("Access Denied: Department Timetable requires '@' in the professor username.", 403)
    return None


# ---------------------------------------------------------------
# Class-teacher timetable builder
# ---------------------------------------------------------------
def build_class_teacher_timetable(
    college_start,
    college_end,
    lecture_minutes,
    practical_minutes,
    batches,
    working_days,
    subjects,
    lunch_start="12:15",
    lunch_minutes=30,
):
    start_min = _parse_hhmm(college_start)
    end_min = _parse_hhmm(college_end)
    lunch_min = _parse_hhmm(lunch_start)

    ordered_subjects = sorted(subjects, key=lambda s: float(s.get("credits", 1)), reverse=True)
    subject_names = [str(s.get("name", "")).strip() for s in ordered_subjects if str(s.get("name", "")).strip()]
    if not subject_names:
        subject_names = ["General Lecture"]

    practical_names = [
        (str(s.get("practical") or f"{str(s.get('name', '')).strip()} Lab")).strip()
        for s in ordered_subjects
        if s.get("has_practical", True) and str(s.get("name", "")).strip()
    ]
    if not practical_names:
        practical_names = [f"{name} Lab" for name in subject_names]

    clean_batches = [str(b).strip() for b in batches if str(b).strip()]

    rows = []
    lec_idx = 0
    prac_rotation = 0

    for day in working_days:
        day_label = str(day).strip()
        cursor = start_min
        lunch_added = False
        day_practical_done = False

        while cursor + lecture_minutes <= end_min:
            if not lunch_added and cursor >= lunch_min:
                lunch_end = min(cursor + lunch_minutes, end_min)
                if lunch_end > cursor:
                    rows.append({
                        "day": day_label,
                        "time": f"{_fmt_hhmm(cursor)} - {_fmt_hhmm(lunch_end)}",
                        "allocation": "LUNCH BREAK",
                        "type": "Break",
                    })
                    cursor = lunch_end
                lunch_added = True
                continue

            if (
                not day_practical_done
                and cursor + practical_minutes <= end_min
                and clean_batches
                and (lunch_added or cursor >= lunch_min or cursor + practical_minutes <= lunch_min)
            ):
                prac_end = cursor + practical_minutes
                batch_slots = []
                for b_idx, batch_name in enumerate(clean_batches):
                    prac_subj = practical_names[(prac_rotation + b_idx) % len(practical_names)]
                    batch_slots.append(f"{prac_subj}-{batch_name}")
                rows.append({
                    "day": day_label,
                    "time": f"{_fmt_hhmm(cursor)} - {_fmt_hhmm(prac_end)}",
                    "allocation": " / ".join(batch_slots),
                    "type": "Practical",
                })
                cursor = prac_end
                prac_rotation += 1
                day_practical_done = True
                continue

            lec_end = cursor + lecture_minutes
            if not lunch_added and cursor < lunch_min < lec_end:
                lec_end = lunch_min

            rows.append({
                "day": day_label,
                "time": f"{_fmt_hhmm(cursor)} - {_fmt_hhmm(lec_end)}",
                "allocation": subject_names[lec_idx % len(subject_names)],
                "type": "Lecture",
            })
            cursor = lec_end
            lec_idx += 1

    markdown_lines = [
        "| Day | Time Slot | Subject / Practical Batches | Type |",
        "|-----|-----------|------------------------------|------|",
    ]
    for r in rows:
        markdown_lines.append(f"| {r['day']} | {r['time']} | {r['allocation']} | {r['type']} |")

    return rows, "\n".join(markdown_lines)


# ---------------------------------------------------------------
# Class-teacher endpoint
# ---------------------------------------------------------------
@coordinator_bp.route("/api/professor/class-teacher/submit", methods=["POST"])
def submit_class_teacher_inputs():
    denied = _professor_error()
    if denied:
        return denied

    data = request.json or {}
    required = ["college_start", "college_end", "lecture_minutes", "practical_minutes",
                "batches", "working_days", "subjects"]
    if any(not data.get(key) for key in required):
        return _error("Please complete all required timetable details.")
    if not isinstance(data.get("working_days"), list) or not data["working_days"]:
        return _error("Select at least one working day.")
    if not isinstance(data.get("subjects"), list) or not data["subjects"]:
        return _error("Add at least one subject with its credits.")
    if not isinstance(data.get("batches"), list):
        return _error("Batches must be a list of batch names.")

    try:
        start_min = _parse_hhmm(data["college_start"])
        end_min = _parse_hhmm(data["college_end"])
    except (TypeError, ValueError, IndexError):
        return _error("College start and end times must look like HH:MM.")
    if end_min <= start_min:
        return _error("College end time must be later than college start time.")

    try:
        lecture_minutes = int(data.get("lecture_minutes"))
        practical_minutes = int(data.get("practical_minutes"))
        batch_count = int(data.get("batch_count", len(data["batches"])))
    except (TypeError, ValueError):
        return _error("Lecture, practical and batch values must be valid numbers.")

    batches = [str(b).strip() for b in data["batches"] if str(b).strip()]
    if lecture_minutes <= 0 or practical_minutes <= 0 or batch_count <= 0 or batch_count != len(batches):
        return _error("Check slot durations and ensure batch names match the batch count.")

    try:
        for item in data["subjects"]:
            if not isinstance(item, dict) or not str(item.get("name", "")).strip() or float(item.get("credits", 0)) <= 0:
                raise ValueError
    except (TypeError, ValueError):
        return _error("Every subject needs a name and a positive credit value.")

    rows, markdown_table = build_class_teacher_timetable(
        college_start=data["college_start"],
        college_end=data["college_end"],
        lecture_minutes=lecture_minutes,
        practical_minutes=practical_minutes,
        batches=batches,
        working_days=data["working_days"],
        subjects=data["subjects"],
    )
    return jsonify({"success": True, "status": "generated", "rows": rows, "timetable": markdown_table})


# ---------------------------------------------------------------
# Department endpoints (username must contain '@')
# ---------------------------------------------------------------
@coordinator_bp.route("/api/professor/department/generate", methods=["POST"])
def generate_department_timetable():
    denied = _professor_error(need_at_symbol=True)
    if denied:
        return denied

    data = request.json or {}
    years_data = data.get("years_data", [])
    curriculum = data.get("curriculum", {})
    staff_records = data.get("staff_records", [])
    labs = data.get("labs", [])
    working_days = data.get("working_days") or DEFAULT_DAYS
    college_start = data.get("college_start", "10:15")

    try:
        batch_size_limit = max(1, int(data.get("batch_size_limit", 25)))
        theory_mins = max(15, int(data.get("theory_mins", 45)))
        practical_mins = max(30, int(data.get("practical_mins", 90)))
        start_min = _parse_hhmm(college_start)
    except (TypeError, ValueError, IndexError):
        return _error("Timing values must be valid numbers.")

    if not years_data or not staff_records:
        return _error("Years data and staff records are required.")

    # ---- practical batches per year / division ----
    calculated_batches = {}
    try:
        for y_info in years_data:
            y_name = y_info["name"]
            total_students = int(y_info["capacity"])
            divs = max(1, int(y_info.get("divisions", 1)))
            stud_per_div = total_students // divs
            prefix = y_name.split()[0][0].lower()
            year_batches = []
            for d_idx in range(divs):
                div_letter = chr(65 + d_idx)
                batches_in_div = max(1, -(-stud_per_div // batch_size_limit))  # ceiling division
                for b_num in range(1, batches_in_div + 1):
                    year_batches.append(f"{y_name} Div {div_letter} - Batch {prefix}{b_num}")
            calculated_batches[y_name] = year_batches
    except (KeyError, TypeError, ValueError, IndexError):
        return _error("Each year needs a name, a capacity and a number of divisions.")

    class_timetables = {}
    teacher_timetables = {s["name"]: {day: [] for day in working_days} for s in staff_records if s.get("name")}

    for y_info in years_data:
        y_name = y_info["name"]
        class_timetables[y_name] = {}
        y_curr = curriculum.get(y_name, {})
        y_subjects = y_curr.get("subjects") or ["General Subject"]
        y_pracs = y_curr.get("practicals") or []

        for day_idx, day in enumerate(working_days):
            cursor = start_min
            day_slots = []

            # rotate subject order so every day is not identical
            shift = day_idx % len(y_subjects)
            for subj in y_subjects[shift:] + y_subjects[:shift]:
                assigned_teacher = "TBD"
                for staff in staff_records:
                    assigned = str(staff.get("assignments", {}).get(y_name, "")).strip()
                    if assigned and assigned != "-" and assigned.lower() == subj.lower():
                        assigned_teacher = staff["name"]
                        break
                slot = {
                    "time": f"{_fmt_hhmm(cursor)} - {_fmt_hhmm(cursor + theory_mins)}",
                    "subject": subj,
                    "type": "Theory",
                    "teacher": assigned_teacher,
                    "year": y_name,
                }
                day_slots.append(slot)
                if assigned_teacher in teacher_timetables:
                    teacher_timetables[assigned_teacher][day].append(slot)
                cursor += theory_mins

            # one practical session per day, rotating through the year's practicals and labs
            if y_pracs:
                prac = y_pracs[day_idx % len(y_pracs)]
                lab = labs[day_idx % len(labs)]["name"] if labs else "General Lab"
                day_slots.append({
                    "time": f"{_fmt_hhmm(cursor)} - {_fmt_hhmm(cursor + practical_mins)}",
                    "subject": prac,
                    "type": "Practical",
                    "lab": lab,
                    "teacher": "Lab Instructor",
                    "year": y_name,
                })

            class_timetables[y_name][day] = day_slots

    record = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "batches": calculated_batches,
        "class_timetables": class_timetables,
        "teacher_timetables": teacher_timetables,
        "labs": labs,
    }

    DEPARTMENT_DATABASE["history"].insert(0, record)
    DEPARTMENT_DATABASE["master_state"] = record
    _save_history(DEPARTMENT_DATABASE["history"])

    return jsonify({
        "success": True,
        "message": "Department master timetable generated successfully!",
        "record": record,
    })


@coordinator_bp.route("/api/professor/department/history", methods=["GET"])
def get_department_history():
    denied = _professor_error(need_at_symbol=True)
    if denied:
        return denied
    return jsonify({"success": True, "history": DEPARTMENT_DATABASE.get("history", [])})