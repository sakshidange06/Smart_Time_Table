<div align="center">

# 🎓 Smart Timetable AI

### Turn your PDFs into quizzes and a personalised daily study plan

An AI-powered study planner built with **Flask**, **PDF text extraction** and the **Groq LLM**, with a **professor module** that generates college class and department timetables.

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
- [Tech Stack](#%EF%B8%8F-tech-stack)
- [Project Structure](#-project-structure)
- [Quick Start](#-quick-start)
- [Configuration](#%EF%B8%8F-configuration)
- [Deployment on Render](#%EF%B8%8F-deployment-on-render)
- [Usage Guide](#-usage-guide)
- [Professor Module](#-professor-module)
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

Professors get a separate portal that builds a **class timetable** (lectures, lunch and practical batches) and a **department master timetable** for several years, divisions, labs and staff.

## ✨ Features

| | Feature | Description |
|---|---|---|
| 🔐 | **Student accounts** | Separate student login with its own session; passwords are stored as hashes |
| 🧠 | **AI Quiz** | Upload a syllabus or notes PDF and get a 5-question multiple-choice quiz with instant scoring |
| 🗓️ | **Smart Timetable** | Upload a college timetable PDF, add wake-up, sleep, dinner and travel times, and get a daily plan with study priorities and productivity tips |
| 🔔 | **Reminders** | Browser notifications for wake-up, study, meals and sleep |
| 📆 | **Google Calendar** | Add the whole plan to your calendar with pop-up reminders and optional daily repeats |
| 📥 | **.ics export** | Download a calendar file that works with any calendar app, no Google setup needed |
| 👩‍🏫 | **Professor accounts** | Separate professor login and session; one role is active per browser at a time |
| 🧑‍🏫 | **Class-teacher timetable** | Generates lectures, lunch break and practical batch rotation from college hours, slot lengths, working days, batches and subject credits |
| 🏛️ | **Department master timetable** | Multi-year timetable with divisions, practical batches, labs, staff allocation, per-teacher timetables and a saved history (username needs `@`) |
| 🖨️ | **Print / Save as PDF** | Print any generated professor timetable from the browser |
| 🛡️ | **Protected files** | Only CSS, JS, images and fonts are served, so source code stays private |

## 🔄 How It Works

```mermaid
flowchart TD
    A[Login / Register] --> B{Choose a tool}
    B --> C[AI Quiz]
    B --> D[Smart Timetable]
    B --> P[Professor Portal]
    C --> C1[Upload syllabus PDF]
    C1 --> C2[Extract text with pypdf]
    C2 --> C3[Groq LLM writes 5 MCQs]
    C3 --> C4[Take the quiz and see your score]
    D --> D1[Upload college timetable PDF]
    D1 --> D2[Enter wake, sleep, dinner, travel times]
    D2 --> D3[Groq LLM builds the daily plan]
    D3 --> D4[Browser reminders]
    D3 --> D5[Google Calendar]
    D3 --> D6[.ics download]
    P --> P1[Class-teacher timetable]
    P --> P2[Department master timetable]
    P1 --> P3[Lectures, lunch, practical batches]
    P2 --> P4[Years, divisions, labs, staff]
    P4 --> P5[Class and teacher timetables plus history]
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
├── app.py                   # Flask app: student login, quiz, timetable, calendar
├── coordinator.py           # Blueprint: professor login, class-teacher and department timetables
├── llm.py                   # Groq LLM setup and configuration
├── index.html               # Web interface (student app + professor portal)
├── requirements.txt         # Python dependencies
├── users.csv                # User accounts (created automatically if missing)
├── department_history.json  # Saved department timetables (created automatically)
├── uploads/                 # Temporary PDF uploads (created automatically, not in Git)
├── .env                     # Local secrets (not in Git)
├── .gitignore
└── README.md
```

The **student login** is in `app.py` and the **professor login** is in `coordinator.py` (a Blueprint registered with `app.register_blueprint(coordinator_bp)`). The shared `users.csv` helpers (hashing, sessions) live in `coordinator.py`, and `app.py` imports them.

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
| `ADMIN_PASSWORD` | | `password123` | Password of the default `admin` account (used when `users.csv` is first created) |
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
1. Register or log in as a student (you stay logged in after a page refresh).
2. Open the **Quiz** tab and upload a syllabus or notes PDF.
3. Answer the generated 5-question quiz and press **Submit Answers** to see your score.

**🗓️ Smart Timetable**
1. Open the **Timetable** tab and upload your college timetable PDF.
2. Enter your wake-up, sleep and dinner times, plus any travel timings.
3. Generate the plan, then enable reminders, add it to Google Calendar, or download the `.ics` file.

**👩‍🏫 Professor**
1. Use the **Professor Portal** button on the login page to register or log in.
2. Choose **class teacher** or **department** timetable (see below).

## 🧑‍🏫 Professor Module

All professor logic lives in `coordinator.py`. Every endpoint needs an active professor session (otherwise `401`).

### Class-teacher timetable

`POST /api/professor/class-teacher/submit`

```json
{
  "college_start": "10:15",
  "college_end": "16:45",
  "lecture_minutes": 60,
  "practical_minutes": 120,
  "batch_count": 3,
  "batches": ["B1", "B2", "B3"],
  "working_days": ["MON", "TUE", "WED", "THU", "FRI", "SAT"],
  "subjects": [
    { "name": "OSY", "credits": 4 },
    { "name": "DBMS", "credits": 3 }
  ]
}
```

The server checks the inputs (valid `HH:MM` times, end after start, positive numbers, `batch_count` equal to the number of batches, every subject with a name and positive credits) and replies with `status: "generated"`, a `rows` list and a Markdown `timetable`. Higher-credit subjects get lectures first, a lunch break is added at 12:15, and each day has one practical slot where batches rotate through the practicals.

### Department master timetable

Requires a professor username that contains **`@`** (for example `name@dept`), otherwise the API returns `403`.

- `POST /api/professor/department/generate` takes years (capacity and divisions), subjects and practicals per year, labs and staff allocation. It returns practical batches, a class timetable per year, a timetable per teacher and a record ID.
- `GET /api/professor/department/history` lists all earlier timetables, newest first, so they can be viewed or printed again.

History is kept in memory and mirrored to `department_history.json`.

## 🔌 API Endpoints

<details>
<summary><b>Click to expand</b></summary>

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Web interface |
| `GET` | `/api/me` | Who is logged in (used to restore the login after a refresh) |
| `POST` | `/api/register` | Register a student *(app.py)* |
| `POST` | `/api/login` | Student login *(app.py)* |
| `POST` | `/api/logout` | Student logout *(app.py)* |
| `POST` | `/api/professor/register` | Register a professor *(coordinator.py)* |
| `POST` | `/api/professor/login` | Professor login *(coordinator.py)* |
| `POST` | `/api/professor/logout` | Professor logout *(coordinator.py)* |
| `POST` | `/api/professor/class-teacher/submit` | Generate a class-teacher timetable *(coordinator.py)* |
| `POST` | `/api/professor/department/generate` | Generate a department master timetable, needs `@` in username *(coordinator.py)* |
| `GET` | `/api/professor/department/history` | List saved department timetables, needs `@` in username *(coordinator.py)* |
| `POST` | `/api/quiz` | Generate a quiz from a PDF (student login required) |
| `POST` | `/api/timetable` | Generate a daily timetable from a PDF and routine (student login required) |
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
- Uploaded PDFs are deleted from the server right after they are processed.
- Passwords are saved as salted hashes. Old plain-text accounts in `users.csv` still log in once and are upgraded automatically.
- Quiz, timetable and calendar endpoints return `401` unless a student is logged in; professor endpoints return `401` unless a professor is logged in.

## ⚠️ Known Limitations

- Accounts are stored in `users.csv`, not in a database yet.
- On the free hosting plan the disk resets on every restart, so accounts and department history on the live site are temporary.
- The department timetable does not yet detect teacher clashes between years.
- Class-teacher timetables are shown on screen only and are not saved.
- Results depend on PDF text quality. Scanned, image-only PDFs cannot be read.

## 🗺️ Roadmap

- [x] Student login and registration
- [x] AI quiz from a syllabus PDF
- [x] Smart daily timetable with reminders
- [x] Google Calendar and `.ics` export
- [x] Professor login and class-teacher timetable generation
- [x] Department master timetable with history
- [x] Separate student (`app.py`) and professor (`coordinator.py`) logins with hashed passwords and sessions
- [ ] Database storage for accounts
- [ ] Teacher and lab clash detection for department timetables
- [ ] Deadline tracking and conflict detection
- [ ] Saved timetable and quiz history for students

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
