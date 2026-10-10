# 🎓 Smart Timetable AI

An AI-powered study planning assistant built with Python, PDF text extraction, and Groq LLM integration. Smart Timetable AI helps students process syllabus PDFs, prepare for quick revision, and plan their study schedules around their daily routines.

## 📌 Project Overview

Students often struggle to manage their study time alongside college schedules, travelling, meals, and sleep. Manually creating a balanced timetable can be time-consuming.

**Smart Timetable AI** aims to simplify academic planning by extracting information from PDF files and preparing it for AI-powered revision and personalized timetable generation.

## 🎯 Objectives

- Extract text from syllabus and college timetable PDFs.
- Support quick revision workflows.
- Collect students' daily routine information.
- Prepare extracted content for AI-based processing.
- Develop personalized study schedules using an LLM.
- Reduce manual effort in study planning.

## ✨ Features

- **User Login:** Basic username and password authentication.
- **PDF Text Extraction:** Extract text from PDF documents using `pypdf`.
- **Text Chunking:** Divide large text into smaller overlapping chunks for LLM processing.
- **Quick Revision Mode:** Process syllabus PDFs for future AI-generated revision material.
- **Smart Timetable Mode:** Read college/school timetable PDFs and collect daily routine details.
- **Groq LLM Integration:** Connect to a language model through LangChain's Groq integration.
- **Environment Variables:** Store credentials and API keys in a local `.env` file.

## 🛠️ Technologies Used

| Technology | Purpose |
|---|---|
| Python | Core programming language |
| PyPDF | PDF text extraction |
| LangChain Groq | LLM integration |
| Groq API | AI model access |
| python-dotenv | Loading environment variables |
| Git & GitHub | Version control and project hosting |

## 📂 Project Structure

```text
Smart-Timetable-AI/
│
├── app.py
├── llm.py
├── requirements.txt
├── .env
├── .gitignore
└── README.md
```

**Note:** The `.env` file is for local use only and must not be uploaded to GitHub.

## ⚙️ Installation and Setup

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
```

Replace `YOUR_USERNAME` and `YOUR_REPOSITORY` with your actual GitHub username and repository name.

### 2. Open the project folder

```bash
cd YOUR_REPOSITORY
```

### 3. Create a virtual environment (recommended)

```bash
python -m venv venv
```

Activate it on Windows:

```bash
venv\Scripts\activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

Your `requirements.txt` should contain:

```text
pypdf
langchain-groq
python-dotenv
```

### 5. Configure environment variables

Create a `.env` file in the project root directory:

```env
GROQ_API_KEY=your_new_groq_api_key
VALID_USERNAME=admin
VALID_PASSWORD=your_demo_password
```

Replace the placeholder values with your own local configuration.

**Security:** Never commit `.env` or share your API key publicly. If an API key has been exposed, revoke it and create a replacement.

### 6. Run the application

```bash
python app.py
```

Follow the terminal prompts to log in and choose an operation.

## 🚀 How to Use

### Option 1: Quick Revision

1. Run the application.
2. Enter your login credentials.
3. Select `1` for Quick Revision.
4. Enter the path to your syllabus PDF.
5. The application extracts the PDF text and divides it into chunks ready for AI processing.

### Option 2: Create Smart Timetable

1. Run the application.
2. Log in.
3. Select `2` for Create Smart Timetable.
4. Enter the path to your college/school timetable PDF.
5. Enter your waking time, sleeping time, dinner time, and travel timings.
6. The application collects this information for the scheduling workflow.

## 🔄 System Workflow

```text
        Start Application
               |
               v
          User Login
               |
               v
       Select Operation
          /         \
         v           v
 Quick Revision   Smart Timetable
         |           |
         v           v
   Syllabus PDF   Timetable PDF
         |           |
         v           v
   Extract Text   Extract Text
         |           |
         v           v
   Text Chunking  Collect Routine
         |           |
         v           v
   AI Processing  AI Scheduling
```

*The AI processing and automatic timetable-generation stages require the corresponding generation logic to be implemented and connected.*

## 🧠 AI Integration

The `llm.py` module initializes a Groq chat model through LangChain. The model can be invoked from `app.py` or another application module to process syllabus content, summarize topics, and generate study plans.

Example:

```python
from llm import llm

response = llm.invoke(
    "Create a simple study plan for Mathematics."
)

print(response.content)
```

The selected model must be available to your Groq account. Model availability may change, so check the current
