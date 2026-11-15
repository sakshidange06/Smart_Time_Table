# coordinator.py
from flask import Blueprint, request, jsonify, session

coordinator_bp = Blueprint("coordinator", __name__)

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

@coordinator_bp.route("/api/professor/department/submit", methods=["POST"])
def submit_department_inputs():
    if session.get("user_role") != "professor" or not session.get("professor_username"):
        return jsonify({"success": False, "message": "Please log in as a professor first."}), 401

    # Stub endpoint prepared for the second part implementation
    return jsonify({
        "success": True,
        "status": "pending",
        "message": "Department timetable module connection is ready."
    })