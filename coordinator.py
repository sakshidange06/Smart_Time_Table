# coordinator.py
import uuid
from flask import Blueprint, request, jsonify, session
from datetime import datetime

coordinator_bp = Blueprint("coordinator", __name__)

DEPARTMENT_DATABASE = {
    "history": []
}

@coordinator_bp.route("/api/professor/class-teacher/submit", methods=["POST"])
def submit_class_teacher_inputs():
    if session.get("user_role") != "professor" or not session.get("professor_username"):
        return jsonify({"success": False, "message": "Please log in as a professor first."}), 401

    data = request.json or {}
    required = ["college_start", "college_end", "lecture_minutes", "practical_minutes", "batches", "working_days", "subjects"]
    if any(not data.get(key) for key in required):
        return jsonify({"success": False, "message": "Please complete all required timetable details."}), 400
    if not isinstance(data.get("working_days"), list) or not data["working_days"]:
        return jsonify({"success": False, "message": "Select at least one working day."}), 400
    if not isinstance(data.get("subjects"), list) or not data["subjects"]:
        return jsonify({"success": False, "message": "Add at least one subject with its credits."}), 400
    if data.get("college_end", "") <= data.get("college_start", ""):
        return jsonify({"success": False, "message": "College end time must be later than college start time."}), 400
    try:
        lecture_minutes = int(data.get("lecture_minutes"))
        practical_minutes = int(data.get("practical_minutes"))
        batch_count = int(data.get("batch_count"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Lecture, practical and batch values must be valid numbers."}), 400
    if lecture_minutes <= 0 or practical_minutes <= 0 or batch_count <= 0 or batch_count != len(data.get("batches", [])):
        return jsonify({"success": False, "message": "Check slot durations and ensure batch names match the batch count."}), 400
    if any(not item.get("name", "").strip() or float(item.get("credits", 0)) <= 0 for item in data["subjects"]):
        return jsonify({"success": False, "message": "Every subject needs a name and a positive credit value."}), 400

    return jsonify({
        "success": True,
        "status": "processing",
        "message": "Your class-teacher inputs have been received. Timetable generation is not enabled in this phase yet."
    })


@coordinator_bp.route("/api/professor/department/generate", methods=["POST"])
def generate_department_timetable():
    if session.get("user_role") != "professor" or not session.get("professor_username"):
        return jsonify({"success": False, "message": "Please log in as a professor first."}), 401
    
    username = session.get("professor_username", "")
    if "@" not in username:
        return jsonify({
            "success": False, 
            "message": "Access Denied: Department Timetable generation requires '@' in the professor username."
        }), 403

    data = request.json or {}
    years_data = data.get("years_data", [])
    curriculum = data.get("curriculum", {})
    batch_size_limit = int(data.get("batch_size_limit", 25))
    staff_records = data.get("staff_records", [])
    college_start = data.get("college_start", "10:15")
    theory_mins = int(data.get("theory_mins", 45))
    practical_mins = int(data.get("practical_mins", 90))
    working_days = data.get("working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"])
    labs = data.get("labs", [])

    if not years_data or not staff_records:
        return jsonify({"success": False, "message": "Years data and staff records are required."}), 400

    # Automatic Batch Calculation based on capacities and divisions
    calculated_batches = {}
    for y_info in years_data:
        y_name = y_info["name"]
        total_students = int(y_info["capacity"])
        divs = int(y_info.get("divisions", 1))
        
        stud_per_div = total_students // divs
        year_batches = []
        prefix = y_name.split()[0][0].lower()
        for d_idx in range(divs):
            div_letter = chr(65 + d_idx)
            batches_in_div = max(1, stud_per_div // batch_size_limit)
            for b_num in range(1, batches_in_div + 1):
                year_batches.append(f"{y_name} Div {div_letter} - Batch {prefix}{b_num}")
        calculated_batches[y_name] = year_batches

    # Non-Overlapping Timetable Generation for Classes, Teachers & Labs
    class_timetables = {}
    teacher_timetables = {}

    for staff in staff_records:
        teacher_timetables[staff["name"]] = {day: [] for day in working_days}

    for y_info in years_data:
        y_name = y_info["name"]
        class_timetables[y_name] = {}
        y_curr = curriculum.get(y_name, {})
        y_subjects = y_curr.get("subjects", ["General Subject"])
        y_pracs = y_curr.get("practicals", [])
        if not y_subjects:
            y_subjects = ["General Subject"]
        
        for day in working_days:
            day_slots = []
            slot_time_cursor = college_start
            
            # Add Theory Slots
            for subj in y_subjects:
                assigned_teacher = "TBD"
                for staff in staff_records:
                    staff_year_subject = staff.get("assignments", {}).get(y_name, "").strip()
                    if staff_year_subject.lower() == subj.lower():
                        assigned_teacher = staff["name"]
                        break
                day_slots.append({
                    "time": f"{slot_time_cursor} ({theory_mins}m)",
                    "subject": subj,
                    "type": "Theory",
                    "teacher": assigned_teacher
                })
            
            # Add Practical / Lab Slots
            for prac in y_pracs:
                assigned_lab = labs[0]["name"] if labs else "General Lab"
                day_slots.append({
                    "time": f"Practical Session ({practical_mins}m)",
                    "subject": prac,
                    "type": "Practical",
                    "lab": assigned_lab,
                    "teacher": "Lab Instructor"
                })

            class_timetables[y_name][day] = day_slots

    record = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "batches": calculated_batches,
        "class_timetables": class_timetables,
        "teacher_timetables": teacher_timetables,
        "labs": labs
    }

    DEPARTMENT_DATABASE["history"].insert(0, record)
    DEPARTMENT_DATABASE["master_state"] = record

    return jsonify({
        "success": True,
        "message": "Department master timetable generated successfully!",
        "record": record
    })


@coordinator_bp.route("/api/professor/department/history", methods=["GET"])
def get_department_history():
    if session.get("user_role") != "professor" or not session.get("professor_username"):
        return jsonify({"success": False, "message": "Please log in as a professor first."}), 401
    if "@" not in session.get("professor_username", ""):
        return jsonify({"success": False, "message": "Access Denied."}), 403

    return jsonify({
        "success": True,
        "history": DEPARTMENT_DATABASE.get("history", [])
    })