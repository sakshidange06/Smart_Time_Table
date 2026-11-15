<div align="center">

# 🎓 Smart Timetable AI

### Turn your PDFs into quizzes and a personalised daily study plan

An AI-powered study planner built with **Flask**, **PDF text extraction** and the **Groq LLM**.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Open%20App-brightgreen?style=for-the-badge&logo=render&logoColor=white)](https://smart-time-table-4gqu.onrender.com)

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-000000?style=flat-square&logo=flask&logoColor=white)
![Groq](https://img.shields.io/badge/LLM-Groq-F55036?style=flat-square)
![LangChain](https://img.shields.io/badge/LangChain-integrated-1C3C3C?style=flat-square)
![Render](https://img.shields.io/badge/Hosted%20on-Render-46E3B7?style=flat-square&logo=render&logoColor=white)
![Google Calendar](https://img.shields.io/badge/Google%20Calendar-API-4285F4?style=flat-square&logo=googlecalendar&logoColor=white)

[Live Demo](https://smart-time-table-4gqu.onrender.com) · [Features](#-features) · [Quick Start](#-quick-start) · [Deployment](#%EF%B8%8F-deployment-on-render) · [API](#-api-endpoints)

</div>

> ⏳ **Note:** the demo runs on a free server that sleeps when idle, so the first load can take **30–60 seconds**.

---

## 📑 Table of Contents

- [About the Project](#-about-the-project)
- [Features](#-features)
- [How It Works](#-how-it-works)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Quick Start](#-quick-start)
- [Configuration](#%EF%B8%8F-configuration)
- [Deployment on Render](#%EF%B8%8F-deployment-on-render)
- [Usage Guide](#-usage-guide)
- [Professor / Coordinator Module](#-professor--coordinator-module)
- [API Endpoints](#-api-endpoints)
- [Security Notes](#-security-notes)
- [Known Limitations](#%EF%B8%8F-known-limitations)
- [Roadmap](#%EF%B8%8F-roadmap)
- [Contributors](#-contributors)

---

## 📌 About the Project

Students often struggle to balance study time with lectures, travelling, meals and sleep. Building a realistic timetable by hand is slow, and revision material takes time to prepare.

**Smart Timetable AI** reads a student's PDFs, combines them with their daily routine, and uses an LLM to:

- generate **multiple-choice quizzes** from syllabus notes, and
- build a **conflict-free daily timetable** around fixed college classes, travel, meals and sleep,

then helps the student stick to it with **reminders** and **calendar export**.

For teachers, a separate **professor / coordinator module** collects the inputs needed to build a college class timetable (working days, slot lengths, batches, subjects and credits).

## ✨ Features

| | Feature | Description |
|---|---|---|
| 🔐 | **Student accounts** | Register and log in with a username and password |
| 👩‍🏫 | **Professor accounts** | Separate professor role with its own login and session |
| 🧑‍🏫 | **Class-teacher form** | Validated input form for college hours, lecture and practical slot lengths, batches, working days, subjects and credits |
| 🏢 | **Department module** | Endpoint prepared for department-level timetable inputs (stub, coming in the next phase) |
| 🧠 | **AI Quiz** | Upload a syllabus or notes PDF and get a 5-question multiple-choice quiz |
| 🗓️ | **Smart Timetable** | Upload a college timetable PDF, add wake-up, sleep, dinner and travel times, and get a daily plan with study priorities and productivity tips |
| 🔔 | **Reminders** | Browser notifications for wake-up, study, meals and sleep |
| 📆 | **Google Calendar** | Add the whole plan to your calendar with pop-up reminders and optional daily repeats |
| 📥 | **.ics export** | Download a calendar file that works with any calendar app, no Google setup needed |
| 🛡️ | **Protected files** | Only CSS, JS, images and fonts are served, so source code stays private |

## 🔄 How It Works

```mermaid
flowchart TD
    A[Login / Register] --> B{Choose a tool}
    B --> C[AI Quiz]
    B --> D[Smart Timetable]
    B --> P[Professor Panel]
    C --> C1[Upload syllabus PDF]
    C1 --> C2[Extract text with pypdf]
    C2 --> C3[Groq LLM writes 5 MCQs]
    C3 --> C4[Take the quiz]
    D --> D1[Upload college timetable PDF]
    D1 --> D2[Enter wake, sleep, dinner, travel times]
    D2 --> D3[Groq LLM builds the daily plan]
    D3 --> D4[Browser reminders]
    D3 --> D5[Google Calendar]
    D3 --> D6[.ics download]
    P --> P1[Class-teacher inputs]
    P --> P2[Department inputs]
    P1 --> P3[Validate and receive inputs]
    P2 --> P4[Stub: connection ready]
    P3 -.-> P5[Timetable generation: planned]
```

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python, Flask (Blueprints), Gunicorn |
| **Frontend** | HTML, CSS, JavaScript (`index.html`) |
| **AI** | Groq API through LangChain (`openai/gpt-oss-20b` by default) |
| **PDF processing** | pypdf |
| **Calendar** | Google Calendar API, iCalendar (`.ics`) |
| **Config** | python-dotenv |
| **Hosting** | Render |
| **Version control** | Git and GitHub |

## 📂 Project Structure

```
Smart_Time_Table/
├── app.py              # Flask app: routes, auth, PDF handling, timetable, calendar
├── coordinator.py      # Flask Blueprint: professor class-teacher and department endpoints
├── llm.py              # Groq LLM setup and configuration
├── index.html          # Web interface
├── requirements.txt    # Python dependencies
├── users.csv           # User accounts (created automatically if missing)
├── uploads/            # Uploaded PDFs (created automatically, not in Git)
├── .env                # Local secrets (not in Git)
├── .gitignore
└── README.md
```

`coordinator.py` defines a Blueprint named `coordinator_bp`. It must be registered once in `app.py`:

```python
from coordinator import coordinator_bp

app.register_blueprint(coordinator_bp)
```

## 🚀 Quick Start

**Prerequisites:** Python 3.10+ and a free [Groq API key](https://console.groq.com).

```bash
# 1. Clone the repository
git clone https://github.com/sakshidange06/Smart_Time_Table.git
cd Smart_Time_Table

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt
```

**4. Create a `.env` file** in the project root. Use no spaces or quotes around the values:

```env
GROQ_API_KEY=your_groq_api_key
FLASK_SECRET_KEY=any_long_random_text
```

**5. Run the app**

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

## ⚙️ Configuration

| Variable | Required | Default | Purpose |
|---|:---:|---|---|
| `GROQ_API_KEY` | ✅ | n/a | Groq API key for the quiz and timetable |
| `FLASK_SECRET_KEY` | ✅ | n/a | Signs login sessions; use a long random string |
| `GROQ_MODEL` | | `openai/gpt-oss-20b` | LLM model name |
| `GROQ_TIMEOUT` | | `60` | Seconds to wait for a model reply |
| `GROQ_MAX_RETRIES` | | `1` | Retries on connection errors |
| `ADMIN_PASSWORD` | | `password123` | Password of the default `admin` account |
| `PYTHON_VERSION` | | Render default | Set to `3.12.8` on Render |

## ☁️ Deployment on Render

> GitHub Pages cannot run this app because it needs a Python backend. Use Render (or a similar host).

1. Push the project to GitHub.
2. On [render.com](https://render.com), choose **New → Web Service** and select this repository.
3. Set the commands:

   | Setting | Value |
   |---|---|
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `gunicorn app:app --workers 1 --threads 4 --timeout 200` |

4. Add the variables from the [Configuration](#%EF%B8%8F-configuration) table in the **Environment** tab (at least `GROQ_API_KEY` and `FLASK_SECRET_KEY`).
5. Click **Create Web Service**. Render redeploys automatically on every push to `main`.

<details>
<summary><b>Optional: enable Google Calendar on Render</b></summary>

1. Create an OAuth client in Google Cloud Console and download `credentials.json`.
2. In Render, open **Environment → Secret Files** and upload it as `credentials.json`.
3. Add `https://YOUR-APP.onrender.com/oauth2callback` to the OAuth client's **Authorized redirect URIs**.

</details>

## 📖 Usage Guide

**🧠 AI Quiz**
1. Register or log in.
2. Open the quiz section and upload a syllabus or notes PDF.
3. Answer the generated 5-question multiple-choice quiz.

**🗓️ Smart Timetable**
1. Log in and open the timetable section.
2. Upload your college timetable PDF.
3. Enter your wake-up, sleep and dinner times, plus any travel timings.
4. Generate the plan, then enable reminders, add it to Google Calendar, or download the `.ics` file.

**👩‍🏫 Professor**
1. Use the **Professor Only** button on the login page to register or log in.
2. Fill in the class-teacher form (college hours, slot lengths, batches, working days, subjects and credits).
3. Submit the form. The inputs are validated and received; timetable generation is coming in a later phase.

## 🧑‍🏫 Professor / Coordinator Module

All professor-side logic lives in `coordinator.py`. Both endpoints require an active professor session (`user_role == "professor"` and a `professor_username`). Without it they return **401**.

### Class-teacher inputs

`POST /api/professor/class-teacher/submit`

**Example request body**

```json
{
  "college_start": "09:00",
  "college_end": "17:00",
  "lecture_minutes": 60,
  "practical_minutes": 120,
  "batch_count": 3,
  "batches": ["A1", "A2", "A3"],
  "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
  "subjects": [
    { "name": "Mathematics", "credits": 4 },
    { "name": "Physics", "credits": 3 }
  ]
}
```

**Validation rules**

| Check | Error (HTTP 400) |
|---|---|
| `college_start`, `college_end`, `lecture_minutes`, `practical_minutes`, `batches`, `working_days`, `subjects` must all be present | Please complete all required timetable details. |
| `working_days` must be a non-empty list | Select at least one working day. |
| `subjects` must be a non-empty list | Add at least one subject with its credits. |
| `college_end` must be later than `college_start` | College end time must be later than college start time. |
| `lecture_minutes`, `practical_minutes` and `batch_count` must be valid numbers | Lecture, practical and batch values must be valid numbers. |
| All three numbers must be greater than 0, and `batch_count` must equal the number of `batches` | Check slot durations and ensure batch names match the batch count. |
| Every subject needs a non-empty name and credits greater than 0 | Every subject needs a name and a positive credit value. |

**Success response**

```json
{
  "success": true,
  "status": "processing",
  "message": "Your class-teacher inputs have been received. Timetable generation is not enabled in this phase yet."
}
```

> Times are compared as `HH:MM` strings, so send them in 24-hour, zero-padded format (for example `09:00`, not `9:00`).

### Department inputs

`POST /api/professor/department/submit`

A stub prepared for the second part of the project. It currently only checks the professor session and returns:

```json
{
  "success": true,
  "status": "pending",
  "message": "Department timetable module connection is ready."
}
```

## 🔌 API Endpoints

<details>
<summary><b>Click to expand</b></summary>

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Web interface |
| `POST` | `/api/register` | Register a student |
| `POST` | `/api/login` | Student login |
| `POST` | `/api/professor/register` | Register a professor |
| `POST` | `/api/professor/login` | Professor login |
| `POST` | `/api/professor/logout` | Professor logout |
| `POST` | `/api/professor/class-teacher/submit` | Validate and receive class-teacher inputs *(coordinator.py)* |
| `POST` | `/api/professor/department/submit` | Department inputs, stub for the next phase *(coordinator.py)* |
| `POST` | `/api/quiz` | Generate a quiz from a PDF |
| `POST` | `/api/timetable` | Generate a daily timetable from a PDF and routine |
| `POST` | `/api/timetable/events` | Parse a timetable into timed events for notifications |
| `POST` | `/api/calendar/add` | Add the timetable to Google Calendar |
| `POST` | `/api/calendar/ics` | Download the timetable as an `.ics` file |
| `GET` | `/google/login` | Start the Google sign-in flow |
| `GET` | `/api/google/status` | Check the Google connection |
| `POST` | `/api/google/disconnect` | Disconnect Google |

</details>

## 🔒 Security Notes

- **Never commit** `.env`, `credentials.json` or real user data. They are listed in `.gitignore`.
- If an API key is ever exposed, revoke it in the Groq console and create a new one.
- Only whitelisted asset types (CSS, JS, images, fonts) can be downloaded from the server.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` when deployed on Render.
- Professor endpoints are protected by a session role check and return `401` for anyone who is not logged in as a professor.

## ⚠️ Known Limitations

- Accounts are stored in `users.csv` with **plain-text passwords**. Moving to a database with hashed passwords is planned.
- On the free hosting plan the disk resets on every restart, so accounts registered on the live site are temporary.
- Professor class-timetable **generation is not implemented yet**; the class-teacher form only validates and receives the inputs.
- The **department module** is a stub and does not process any data yet.
- Submitted class-teacher inputs are not saved anywhere yet.
- Results depend on PDF text quality. Scanned, image-only PDFs cannot be read.

## 🗺️ Roadmap

- [x] Student login and registration
- [x] AI quiz from a syllabus PDF
- [x] Smart daily timetable with reminders
- [x] Google Calendar and `.ics` export
- [x] Professor login and class-teacher input form
- [x] Coordinator Blueprint with validated class-teacher endpoint and department stub
- [ ] Department timetable module (second phase)
- [ ] Automatic class timetable generation for professors
- [ ] Database storage with hashed passwords
- [ ] Deadline tracking and conflict detection
- [ ] Saved timetable and quiz history

## 👥 Contributors

<table>
  <tr>
    <td align="center"><a href="https://github.com/sakshidange06"><b>@sakshidange06</b></a></td>
    <td align="center"><a href="https://github.com/shraddhadange31-png"><b>@shraddhadange31-png</b></a></td>
    <td align="center"><a href="https://github.com/SejalGawali"><b>@SejalGawali</b></a></td>
  </tr>
</table>

---

<div align="center">

⭐ If you find this project useful, please give it a star!

</div>
