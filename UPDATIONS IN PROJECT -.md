UPDATIONS IN PROJECT :-



**How to Make It Handle 100 Users Much Better**

Use Gunicorn with Enough Workers/Threads on Render:



Start with e.g. gunicorn --workers 2 --threads 4 --timeout 120 app:app (tuned to your Render plan's RAM—don't over-allocate workers on a 512 MB instance).



Use PostgreSQL (DATABASE\_URL) Instead of CSV/Local SQLite:



Prevents write contention and keeps users persistent across deploys and workers.



Add Basic Guardrails on Heavy AI Routes:



Enforce a max upload file size (e.g., app.config\["MAX\_CONTENT\_LENGTH"] = 10 \* 1024 \* 1024), return clear JSON errors on rate limits/timeouts, and delete temporary PDFs after extracting text if you don't need to keep them.



Run a small load test (such as locust or hey / ab) against /, /api/login, and /api/quiz with realistic concurrency to see exact response times and error rates on your actual Render plan.


Future plans :- 
**Using two AI agents—one for students and one for professors—is a great idea for clean design and tailored prompts, not a magic fix for handling 100 concurrent users.**

1\. What Two Agents Help With (Architecture \& Quality)

Different Goals \& Rules: A Student Agent focuses on personal study schedules, meals/sleep/travel routines, and revision quizzes from notes. A Professor Agent focuses on academic constraints (credits, lecture vs. practical slots, batch rotations, lab/faculty assignments).



Cleaner Prompts \& Fewer Mistakes: Keeping student and professor instructions separate prevents one role's rules from bleeding into the other's responses.



Role-Based Access: You can keep the professor agent strictly behind professor session/role checks, separate from student routes.



