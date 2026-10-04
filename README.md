# ClassTracker

A shared class calendar. The admin manages subjects and accounts; users enroll in subjects and see meetings, tasks, and exams for those subjects on a monthly calendar. Users the admin has allowed can also add entries. The admin can also post announcements that appear for everyone until they close them.

Built with Python + Flask, deployed on Vercel.

## Run locally (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m flask --app app run --debug
```

Then open http://127.0.0.1:5000.

## Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```
