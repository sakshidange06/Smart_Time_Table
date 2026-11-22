# coordinator.py
# Professor login + professor services (class-teacher and department timetables).
# Uses db.py (SQLAlchemy) for user storage and department timetable history,
# with conflict-aware department scheduling and credit-weighted subject slots.
import json
import uuid
from datetime import datetime
from functools import wraps
from llm import llm
from flask import Blueprint, jsonify, request, session
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from db import (
    ChatSessionRecord,
    TimetableRecord,
    UserRecord,
    get_db_session,
)

coordinator_bp = Blueprint("coordinator", __name__)

# ===============================================================
# USER STORE (SQLAlchemy), PASSWORD HASHING AND SESSION HELPERS
# ===============================================================
MIN_PASSWORD_LENGTH = 6
_HASH_PREFIXES = ("pbkdf2:", "scrypt:")
_DEPARTMENT_SESSION_ID = "dept_history:shared"
DEFAULT_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def _is_hashed(value):
    return isinstance(value, str) and value.startswith(_HASH_PREFIXES)


def _role_matches(record_role, wanted_role):
    return ((record_role or "student").strip().lower() == "professor") == (
        (wanted_role or "student").strip().lower() == "professor"
    )


def _normalize_role(role):
    return "professor" if str(role or "").strip().lower() == "professor" else "student"


# ---------------------------------------------------------------
# Register / verify (backed by db.py UserRecord)
# ---------------------------------------------------------------
def register_user(username, password, role):
    """Create an account in the database. Returns (ok, message)."""
    clean_user = str(username or "").strip()
    clean_password = str(password or "").strip()
    clean_role = _normalize_role(role)

    if not clean_user or not clean_password:
        return False, "Username and password cannot be empty."
    if len(clean_user) < 3 or any(ch in clean_user for ch in ",\r\n"):
        return False, "Username must be at least 3 characters and cannot contain commas."
    if len(clean_password) < MIN_PASSWORD_LENGTH:
        return False, f"Use a password with at least {MIN_PASSWORD_LENGTH} characters."

    try:
        with get_db_session() as db:
            existing = db.execute(
                select(UserRecord.id).where(UserRecord.username == clean_user)
            ).scalar_one_or_none()
            if existing is not None:
                return False, "Username already exists. Please choose another."

            db.add(
                UserRecord(
                    username=clean_user,
                    password_hash=generate_password_hash(clean_password),
                    role=clean_role,
                )
            )
            db.flush()
        return True, "Registration successful!"
    except IntegrityError:
        return False, "Username already exists. Please choose another."
    except Exception as exc:
        print("REGISTER USER ERROR:", repr(exc))
        return False, "Database error while registering user."


def verify_user(username, password, role):
    """Check a login for the given role ("student" or "professor")."""
    clean_user = str(username or "").strip()
    clean_password = str(password or "").strip()
    if not clean_user or not clean_password:
        return False

    try:
        with get_db_session() as db:
            user = db.execute(
                select(UserRecord).where(UserRecord.username == clean_user)
            ).scalar_one_or_none()
            if user is None or not _role_matches(user.role, role):
                return False

            stored = user.password_hash or ""
            if _is_hashed(stored):
                return check_password_hash(stored, clean_password)
            if stored == clean_password:
                user.password_hash = generate_password_hash(clean_password)
                db.add(user)
                return True
            return False
    except Exception as exc:
        print("VERIFY USER ERROR:", repr(exc))
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
    ok, message = register_user(
        data.get("username", ""),
        data.get("password", ""),
        role="professor",
    )
    return jsonify({"success": ok, "message": message}), (200 if ok else 400)


@coordinator_bp.route("/api/professor/login", methods=["POST"])
def professor_login():
    data = request.json or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if verify_user(username, password, role="professor"):
        start_session("professor", username)
        return jsonify({
            "success": True,
            "username": username,
            "message": "Professor login successful.",
        })
    return jsonify({"success": False, "message": "Invalid professor username or password."}), 401


@coordinator_bp.route("/api/professor/logout", methods=["POST"])
def professor_logout():
    end_session("professor")
    return jsonify({"success": True, "message": "Professor logged out."})


# ---------------------------------------------------------------
# Department history (backed by db.py TimetableRecord)
# ---------------------------------------------------------------
def _get_or_create_dept_owner(db, username: str) -> UserRecord:
    clean_name = (username or "admin").strip()
    user = db.execute(
        select(UserRecord).where(UserRecord.username == clean_name)
    ).scalar_one_or_none()
    if user is not None:
        return user

    admin_user = db.execute(
        select(UserRecord).where(UserRecord.username == "admin")
    ).scalar_one_or_none()
    if admin_user is not None:
        return admin_user

    fallback_user = UserRecord(
        username=clean_name,
        password_hash=generate_password_hash("password123"),
        role="professor",
    )
    db.add(fallback_user)
    db.flush()
    return fallback_user


def _get_or_create_dept_session(db, username: str) -> ChatSessionRecord:
    owner = _get_or_create_dept_owner(db, username)
    sess = db.execute(
        select(ChatSessionRecord).where(ChatSessionRecord.session_id == _DEPARTMENT_SESSION_ID)
    ).scalar_one_or_none()
    if sess is None:
        sess = ChatSessionRecord(
            session_id=_DEPARTMENT_SESSION_ID,
            user_id=owner.id,
            title="Department Master Timetable History",
        )
        db.add(sess)
        db.flush()
    return sess


def _save_department_record(record: dict, username: str) -> None:
    try:
        with get_db_session() as db:
            dept_sess = _get_or_create_dept_session(db, username)
            db.add(
                TimetableRecord(
                    session_id=dept_sess.id,
                    department="Department Master",
                    payload_json=json.dumps(record, ensure_ascii=False),
                )
            )
    except Exception as exc:
        print("DEPARTMENT RECORD SAVE ERROR:", repr(exc))


def _load_department_history() -> list:
    history = []
    try:
        with get_db_session() as db:
            rows = db.execute(
                select(TimetableRecord)
                .where(TimetableRecord.department == "Department Master")
                .order_by(desc(TimetableRecord.id))
            ).scalars().all()
            for row in rows:
                try:
                    parsed = json.loads(row.payload_json)
                    if isinstance(parsed, dict):
                        history.append(parsed)
                except (TypeError, ValueError):
                    continue
    except Exception as exc:
        print("DEPARTMENT HISTORY LOAD ERROR:", repr(exc))
    return history


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
    username = session.get("professor_username", "")
    if session.get("user_role") != "professor" or not username:
        return _error("Please log in as a professor first.", 401)
    if need_at_symbol and "@" not in username:
        return _error("Access Denied: Department Timetable requires '@' in the professor username.", 403)
    return None


def _build_weighted_subject_pool(ordered_subjects):
    pool = []
    for s in ordered_subjects:
        name = str(s.get("name", "")).strip()
        if not name:
            continue
        weight = max(1, min(6, round(float(s.get("credits", 1)))))
        pool.extend([name] * weight)
    return pool or ["General Lecture"]


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
    subject_pool = _build_weighted_subject_pool(ordered_subjects)
    unique_subjects = list(dict.fromkeys(subject_pool))

    practical_names = [
        (str(s.get("practical") or f"{str(s.get('name', '')).strip()} Lab")).strip()
        for s in ordered_subjects
        if s.get("has_practical", True) and str(s.get("name", "")).strip()
    ]
    if not practical_names:
        practical_names = [f"{name} Lab" for name in unique_subjects]

    clean_batches = [str(b).strip() for b in batches if str(b).strip()]

    rows = []
    pool_idx = 0
    prac_rotation = 0
    last_lecture_subj = None

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

            chosen_subj = subject_pool[pool_idx % len(subject_pool)]
            if len(unique_subjects) > 1 and chosen_subj == last_lecture_subj:
                for offset in range(1, len(subject_pool) + 1):
                    candidate = subject_pool[(pool_idx + offset) % len(subject_pool)]
                    if candidate != last_lecture_subj:
                        chosen_subj = candidate
                        break

            rows.append({
                "day": day_label,
                "time": f"{_fmt_hhmm(cursor)} - {_fmt_hhmm(lec_end)}",
                "allocation": chosen_subj,
                "type": "Lecture",
            })
            last_lecture_subj = chosen_subj
            cursor = lec_end
            pool_idx += 1

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
                batches_in_div = max(1, -(-stud_per_div // batch_size_limit))
                for b_num in range(1, batches_in_div + 1):
                    year_batches.append(f"{y_name} Div {div_letter} - Batch {prefix}{b_num}")
            calculated_batches[y_name] = year_batches
    except (KeyError, TypeError, ValueError, IndexError):
        return _error("Each year needs a name, a capacity and a number of divisions.")

    class_timetables = {}
    teacher_timetables = {
        s["name"]: {day: [] for day in working_days}
        for s in staff_records
        if s.get("name")
    }
    busy_teachers = set()
    busy_labs = set()
    lab_names = [
        str(l.get("name", "")).strip()
        for l in labs
        if isinstance(l, dict) and str(l.get("name", "")).strip()
    ] or ["General Lab"]

    for y_idx, y_info in enumerate(years_data):
        y_name = y_info["name"]
        class_timetables[y_name] = {}
        y_curr = curriculum.get(y_name, {})
        y_subjects = y_curr.get("subjects") or ["General Subject"]
        y_pracs = y_curr.get("practicals") or []

        for day_idx, day in enumerate(working_days):
            cursor = start_min
            day_slots = []

            shift = (day_idx + y_idx) % len(y_subjects)
            for subj in y_subjects[shift:] + y_subjects[:shift]:
                slot_label = f"{_fmt_hhmm(cursor)} - {_fmt_hhmm(cursor + theory_mins)}"
                assigned_teacher = "TBD"

                for staff in staff_records:
                    staff_name = str(staff.get("name", "")).strip()
                    if not staff_name:
                        continue
                    assigned = str(staff.get("assignments", {}).get(y_name, "")).strip()
                    if assigned and assigned != "-" and assigned.lower() == subj.lower():
                        if (day, slot_label, staff_name) not in busy_teachers:
                            assigned_teacher = staff_name
                            busy_teachers.add((day, slot_label, staff_name))
                            break

                slot = {
                    "time": slot_label,
                    "subject": subj,
                    "type": "Theory",
                    "teacher": assigned_teacher,
                    "year": y_name,
                }
                day_slots.append(slot)
                if assigned_teacher in teacher_timetables:
                    teacher_timetables[assigned_teacher][day].append(slot)
                cursor += theory_mins

            if y_pracs:
                prac = y_pracs[(day_idx + y_idx) % len(y_pracs)]
                slot_label = f"{_fmt_hhmm(cursor)} - {_fmt_hhmm(cursor + practical_mins)}"
                chosen_lab = lab_names[(day_idx + y_idx) % len(lab_names)]
                for candidate_lab in lab_names:
                    if (day, slot_label, candidate_lab) not in busy_labs:
                        chosen_lab = candidate_lab
                        break
                busy_labs.add((day, slot_label, chosen_lab))

                day_slots.append({
                    "time": slot_label,
                    "subject": prac,
                    "type": "Practical",
                    "lab": chosen_lab,
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

    username = session.get("professor_username", "admin")
    _save_department_record(record, username)
    history = _load_department_history()

    return jsonify({
        "success": True,
        "message": "Department master timetable generated successfully!",
        "record": record,
        "history": history,
    })


@coordinator_bp.route("/api/professor/department/history", methods=["GET"])
def get_department_history():
    denied = _professor_error(need_at_symbol=True)
    if denied:
        return denied
    return jsonify({"success": True, "history": _load_department_history()})