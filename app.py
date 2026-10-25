import os
import csv
import json
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
from pypdf import PdfReader
from langchain_core.prompts import ChatPromptTemplate
from llm import llm

app = Flask(__name__, template_folder='.', static_folder='.')

UPLOAD_FOLDER = 'uploads'
USER_CSV = 'users.csv'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def init_user_csv():
    if not os.path.exists(USER_CSV):
        with open(USER_CSV, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['username', 'password'])
            writer.writerow(['admin', 'password123'])


init_user_csv()


def verify_credentials(username, password):
    with open(USER_CSV, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['username'] == username and row['password'] == password:
                return True
    return False


def register_new_user(username, password):
    with open(USER_CSV, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['username'] == username:
                return False, 'Username already exists.'

    with open(USER_CSV, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([username, password])

    return True, 'Registration successful!'


def extract_pdf_text(pdf_path):
    reader = PdfReader(pdf_path)
    text = ''

    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + '\n'

    return text


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if verify_credentials(username, password):
        return jsonify({'success': True, 'message': 'Login successful!'})

    return jsonify({
        'success': False,
        'message': 'Invalid username or password.'
    }), 401


@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({
            'success': False,
            'message': 'Username and password cannot be empty.'
        }), 400

    success, message = register_new_user(username, password)

    return jsonify({'success': success, 'message': message})


@app.route('/api/quiz', methods=['POST'])
def generate_quiz():
    if 'pdf' not in request.files:
        return jsonify({'success': False, 'message': 'No PDF provided.'}), 400

    file = request.files['pdf']

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'success': False, 'message': 'Please upload a PDF.'}), 400

    filename = secure_filename(file.filename)
    pdf_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(pdf_path)

    try:
        text = extract_pdf_text(pdf_path)

        if not text.strip():
            return jsonify({
                'success': False,
                'message': 'No text found in PDF.'
            }), 400

        prompt = ChatPromptTemplate.from_messages([
            ('system',
             'Generate 5 multiple-choice questions from the notes. '
             'Return only a valid JSON array. Each object must contain '
             'id, question, options, and answer.'),
            ('human', 'Notes:\n{text}')
        ])

        response = (prompt | llm).invoke({'text': text[:1500]})
        content = response.content.strip()
        content = content.removeprefix('```json').removesuffix('```').strip()

        quiz = json.loads(content)

        return jsonify({'success': True, 'quiz': quiz})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/timetable', methods=['POST'])
def generate_timetable():
    if 'pdf' not in request.files:
        return jsonify({'success': False, 'message': 'No PDF provided.'}), 400

    file = request.files['pdf']

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'success': False, 'message': 'Please upload a PDF.'}), 400

    filename = secure_filename(file.filename)
    pdf_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(pdf_path)

    try:
        text = extract_pdf_text(pdf_path)

        if not text.strip():
            return jsonify({
                'success': False,
                'message': 'No text found in PDF.'
            }), 400

        prompt = ChatPromptTemplate.from_messages([
            ('system',
             'You are an AI study planner. Create a balanced daily '
             'routine based on the college timetable and user details. '
             'Use headings and bullet points.'),
            ('human',
             'College timetable:\n{text}\n'
             'Wake-up time: {wake_time}\n'
             'Sleep time: {sleep_time}\n'
             'Dinner time: {dinner_time}\n'
             'Travel time: {travel_timestamps}')
        ])

        response = (prompt | llm).invoke({
            'text': text[:4000],
            'wake_time': request.form.get('wake_time', 'Not specified'),
            'sleep_time': request.form.get('sleep_time', 'Not specified'),
            'dinner_time': request.form.get('dinner_time', 'Not specified'),
            'travel_timestamps': request.form.get(
                'travel_timestamps', 'Not specified'
            )
        })

        return jsonify({
            'success': True,
            'timetable': response.content
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)