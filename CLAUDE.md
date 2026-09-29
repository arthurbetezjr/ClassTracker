# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

ClassTracker is a shared class calendar webapp. Only the project skeleton exists so far; the plan below is agreed.

## Commands (PowerShell, from the repo root)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # install deps
.\.venv\Scripts\python.exe -m flask --app app run --debug          # run at http://127.0.0.1:5000
.\.venv\Scripts\python.exe -m pytest                                # all tests
.\.venv\Scripts\python.exe -m pytest tests/test_home.py::test_home_page_loads   # one test
```

## Layout

- `app.py`: entry point. Exposes `app = create_app()`, which Vercel and `flask --app app` both look for.
- `classtracker/`: the application package (`create_app` lives in `__init__.py`, templates in `templates/`).
- `requirements.txt`: runtime deps, which Vercel installs. `requirements-dev.txt` adds test tools.
- Static assets come from CDNs (Bootstrap, FullCalendar). Anything self-hosted must go in `public/`, because Vercel serves static files from there, not from Flask's static folder.

## Stack

- **Python + Flask** server with HTML templates (Jinja) and Bootstrap
- **FullCalendar** for the monthly calendar view
- **Postgres on Neon**, connected through Vercel's Storage integration. The connection string comes from the `DATABASE_URL` environment variable. Local development uses a separate Neon branch, not the production database.
- **SQLAlchemy** for database access
- Deployed on **Vercel** (Python runtime, serverless), auto-deployed from GitHub `main`. Serverless means no local files persist between requests, so all state goes in Postgres and sessions use signed cookies.
- Passwords are stored as hashes only.

## Domain rules

- Roles: `admin` and `user`. A default `admin` account (password `12345`) is seeded and must change its password on first login. Usernames can't be changed.
- Only the admin creates, edits, and deletes accounts.
- Subjects: `code` is the unique ID and can't be changed after creation. Deleting a subject deletes its entries and enrollments, after a warning.
- Users enroll in subjects. They see calendar entries only for the subjects they're enrolled in; the admin sees all entries.
- Entries: type is Cycle Meeting, Task, or Exam, each shown in its own color. Each entry has a unique readable ID (for example `E-00042`). Subject code and date are required. Time, meeting link (Meetings only), and instructions are optional.
- Users can add entries only in subjects they're enrolled in, and can edit or delete only their own entries. The admin can edit or delete any entry and must give a reason.
- Deleted entries are soft-deleted: they stay visible to everyone in the subject, marked deleted, with the reason. Reasons for edits appear only in the admin's change log.
- Deleting a user keeps the entries they created.

## Repository

- Remote: `origin` → https://github.com/arthurbetezjr/ClassTracker.git, default branch `main`
- Development happens on Windows (PowerShell).

## Working with the owner

This is the owner's first webapp. Explain what each step does and why, in plain terms, and prefer simple, well-documented tooling over clever setups.
