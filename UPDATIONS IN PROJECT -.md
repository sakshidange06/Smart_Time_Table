UPDATIONS IN PROJECT :-



**How to Make It Handle 100 Users Much Better**

Use Gunicorn with Enough Workers/Threads on Render:



Start with e.g. gunicorn --workers 2 --threads 4 --timeout 120 app:app (tuned to your Render plan's RAM—don't over-allocate workers on a 512 MB instance).



Use PostgreSQL (DATABASE\_URL) Instead of CSV/Local SQLite:



Prevents write contention and keeps users persistent across deploys and workers.



Add Basic Guardrails on Heavy AI Routes:



Enforce a max upload file size (e.g., app.config\["MAX\_CONTENT\_LENGTH"] = 10 \* 1024 \* 1024), return clear JSON errors on rate limits/timeouts, and delete temporary PDFs after extracting text if you don't need to keep them.



Test Before Demo/Exam/Launch Day:



Run a small load test (such as locust or hey / ab) against /, /api/login, and /api/quiz with realistic concurrency to see exact response times and error rates on your actual Render plan.



If you'd like to share your Render plan/start command or requirements.txt, I can give you concrete tuning values for your exact setup.





**Using two AI agents—one for students and one for professors—is a great idea for clean design and tailored prompts, not a magic fix for handling 100 concurrent users.**



1\. What Two Agents Help With (Architecture \& Quality)

Different Goals \& Rules: A Student Agent focuses on personal study schedules, meals/sleep/travel routines, and revision quizzes from notes. A Professor Agent focuses on academic constraints (credits, lecture vs. practical slots, batch rotations, lab/faculty assignments).



Cleaner Prompts \& Fewer Mistakes: Keeping student and professor instructions separate prevents one role's rules from bleeding into the other's responses.



Role-Based Access: You can keep the professor agent strictly behind professor session/role checks, separate from student routes.



2\. What Two Agents Do Not Solve (100 Concurrent Users)

Shared API Rate Limits: If both agents use the same GROQ\_API\_KEY / model tier, 100 simultaneous requests still share your account's requests-per-minute (RPM) and tokens-per-minute (TPM) limits.



Same Web Workers \& Timeouts: Unless you use background workers/queues or async handling, synchronous Flask/Gunicorn requests waiting on LLM responses still occupy workers and risk timeouts under heavy bursts.



Deterministic vs. AI for Timetables: In your current coordinator.py, class teacher and department timetables are generated with deterministic Python logic, which is faster, cheaper, and more predictable than asking an LLM to schedule slots—whereas an LLM is more helpful for suggestions, conflict explanations, or timetable updates/upkeep.



Practical Way to Structure It in Your Project

Student Agent: Handles PDF quiz generation (/api/quiz) and personalized daily study/routine planning (/api/timetable).



Professor Agent: Keep deterministic scheduling in coordinator.py for speed and reliability, and optionally use a dedicated professor LLM chain/agent for tasks like smart timetable updates/adjustments, workload/clash checking summaries, or syllabus/course notes.



For 100 Users: Pair clean agent separation with PostgreSQL (DATABASE\_URL), Gunicorn workers/threads, upload size limits + temp file cleanup, and graceful retry/error messages when Groq is rate-limited.



Are you thinking of using the professor AI agent to modify/update existing timetables (matching "with updations" in your department view), or to generate full schedules from scratch?











"Now let's do suggested part 1: fix the frontend \& backend bugs."



"Now let's do suggested part 2: upgrade the timetable scheduler."



"Now let's do suggested part 3: improve quiz coverage."

