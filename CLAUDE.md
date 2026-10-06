# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

ClassTracker is a shared class calendar webapp. Build plan: 1 setup, 2 login, 3 accounts, 4 subjects/enrollment, 5 entries, 6 calendar, 7 polish. All 7 steps are done; further work is feature requests from the owner.

## Commands (PowerShell, from the repo root)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # install deps
.\.venv\Scripts\python.exe -m flask --app app run --debug          # run at http://127.0.0.1:5000
.\.venv\Scripts\python.exe -m pytest                                # all tests
.\.venv\Scripts\python.exe -m pytest tests/test_auth.py::test_logout_ends_session   # one test
```

## Layout

- `app.py`: entry point. Exposes `app = create_app()`, which Vercel and `flask --app app` both look for.
- `classtracker/__init__.py`: `create_app()` loads config from env, wires extensions and blueprints, enforces login on every endpoint except `PUBLIC_ENDPOINTS` (and forces a password change when `must_change_password` is set), then runs `db.create_all()` and seeds the default admin. This runs on every cold start.
- `classtracker/models.py`: the whole schema (users, subjects, enrollments, entries, entry_changes, announcements, announcement_dismissals).
- One blueprint per feature area (`auth.py`, `accounts.py`, `subjects.py`, `entries.py`, `announcements.py`); `extensions.py` holds the shared `db`, `login_manager`, `csrf` objects. Admin-only views use `auth.admin_required` (the accounts blueprint applies it to every route via `before_request`; announcements applies it per route because `dismiss` is open to all users).
- `/subjects/` renders a different template per role: admin management (`subjects/admin_index.html`) vs. user enrollment cards (`subjects/user_index.html`). Subject codes are stored uppercase, no spaces.
- Deleting a subject relies on database `ON DELETE CASCADE` for its entries (the ORM relationship uses `passive_deletes`); their `entry_changes` rows stay, with `entry_id` set to NULL. Tests turn on SQLite foreign keys in `conftest.py` so this behaves like Postgres.
- `entries.py` owns the permission rules: `visible_entries()` (the base query for anything that lists entries, including the calendar), `allowed_subjects()`, `can_change()`, `edit_needs_reason()`. Reuse them rather than re-deriving access rules.
- The home page `/` is the calendar (`templates/calendar.html`, FullCalendar 6 from jsDelivr). It loads events as JSON from `entries.calendar_feed` (`/entries/calendar-feed?start&end[&subject][&types]`), which is built on `visible_entries()`. Clicking an empty day opens `/entries/new?date=...`.
- Calendar times are always written in full, e.g. `9:00am` and `7:30am` (owner's rule, 2026-10-05): no `9a`/`7:30a` shortcuts in any view. One `eventTimeFormat` in `calendar.html` covers both views. The entry page's back link goes to the calendar.
- `timeutil.py`: "today" and timestamp display use `APP_TIMEZONE`; Jinja filters `nice_date`, `nice_time`, `local_timestamp`. `ENTRY_TYPES` / `ENTRY_COLORS` are available in every template. Templates importing `entries/_macros.html` must use `with context`.
- Design: `base.html` holds the whole theme as inline CSS (Bootstrap 5.3 CSS variables, dark by default via `data-bs-theme`, light/dark toggle saved in `localStorage` as `ct-theme`) plus the brand gradient `--ct-grad` (violet → pink → orange). Entry types are drawn with `ENTRY_GRADIENTS` (models.py) through `.ct-type.ct-type-<key>` badges and `.fc-daygrid-event.ct-type-<key>` calendar events. The logo is an inline SVG macro in `templates/_logo.html` (also used as the favicon data URI). The footer credits the developer (Arthur Betez Jr.) and must stay.
- Keep the UI minimalist; the owner asked for that explicitly.
- Meeting links are forced to http(s) in `entries.clean()` because they're rendered as `href`s.
- Usernames are stored lowercase (`auth.normalize_username`) and login ignores case. The admin account can't be deleted or reset from the Accounts page.
- The Accounts page also has a bulk form (`accounts.create_many`, `POST /accounts/bulk`): one username per line plus a shared starting password. It skips existing usernames and creates nothing if any line is invalid. It was built (2026-10-01) to add the 46-student class roster.
- Announcements (`announcements.py`, added 2026-10-01): the admin posts and deletes them at `/announcements/`. Regular users see a read-only list of all announcements there (`announcements/user_index.html`, added 2026-10-04), including ones they closed; the closable cards are hidden on that page. A context processor passes `open_announcements` (ones the current user hasn't closed) to every template, and `base.html` draws them as cards above the page content. The × button posts to `announcements.dismiss` in the background (`X-Requested-With: fetch` gets a 204; a plain form post redirects back) and stores a row in `announcement_dismissals`.
- Usage (`usage.py`, added 2026-10-06): admin-only `/usage/` page ("Usage" tab after Accounts) with Online now / Today / This month / This year counts of distinct students, who's online, and every student's last-seen time. `require_login` calls `usage.record_activity(current_user)` after the login check (so a student with a pending password change counts too). It upserts one row per student per local day in `user_activity_days` (`user_id`, `day` in `APP_TIMEZONE`, `last_seen_at` UTC), but at most every `SAVE_INTERVAL` (5 min): the session key `ct_seen` = `{u: user id, t: last save}` lets most requests skip the database entirely; a new user id or a new local day forces a save. Failures are logged and swallowed so a page never breaks. Admins aren't recorded or listed. All counts are queries at page load; nothing else is stored (no IPs, URLs, user agents). Rows are kept forever and cascade away with the user. This feature added only that one new table (created by `create_all()`); no existing table was changed.
- Tests set `PASSWORD_HASH_METHOD` to a cheap pbkdf2 so the suite runs in seconds; production uses scrypt.
- Tests: `admin_client` fixture in `tests/conftest.py` is logged in as admin with the first-login password change done; `switch_to_new_user` / `switch_to_admin` swap the logged-in account (`switch_to_new_user` turns on entry posting unless `allow_entries=False`).
- Every POST form must include `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` (Flask-WTF CSRFProtect).
- Tests use in-memory SQLite with CSRF disabled (`tests/conftest.py`); keep models portable between SQLite and Postgres.
- `requirements.txt`: runtime deps, which Vercel installs. `requirements-dev.txt` adds test tools.
- Static assets come from CDNs (Bootstrap, FullCalendar). Anything self-hosted must go in `public/`, because Vercel serves static files from there, not from Flask's static folder.

## Stack

- **Python + Flask** server with HTML templates (Jinja) and Bootstrap
- **FullCalendar** for the monthly calendar view
- **Postgres on Neon**, connected through Vercel's Storage integration. The connection string comes from the `DATABASE_URL` environment variable. Local development uses a separate Neon branch, not the production database.
- **SQLAlchemy 2** (via Flask-SQLAlchemy), **Flask-Login** for sessions, **Flask-WTF** for CSRF
- There are no migrations: `create_all()` only creates missing tables. To add a column to a table that already exists in Neon, add the model field *and* an entry to `ADDED_COLUMNS` in `classtracker/__init__.py`, which adds it on startup if it's missing. Anything beyond adding columns (renames, type changes) needs a manual `ALTER TABLE` on both the `dev` and production branches.
- Deployed on **Vercel** (Python runtime, serverless), auto-deployed from GitHub `main`. The Vercel project's Framework Preset must be **Flask**; with "Other" every URL returns 404.
- Regions: Vercel functions run in `iad1` (Washington, D.C.) and the Neon database is in `us-east-1`, so they sit next to each other, but users in the Philippines see about 0.4s per request. On 2026-10-04 the owner decided not to move to Singapore. Moving means both a new Neon project in `aws-ap-southeast-1` (Neon can't change a project's region) with the data copied over, and the Vercel Function Region set to `sin1`. Never move only one of the two.
- Serverless means no local files persist between requests, so all state goes in Postgres and sessions use signed cookies.
- Required env vars: `DATABASE_URL` and `SECRET_KEY`. Optional: `APP_TIMEZONE` (IANA name, default `Asia/Manila`, where the users are). Locally they're in `.env` (git-ignored; `DATABASE_URL` points to the Neon `dev` branch). On Vercel they're set in the project's Environment Variables.
- Passwords are stored as hashes only.

## Domain rules

- Roles: `admin` and `user`. A default `admin` account (password `12345`) is seeded and must change its password on first login. Usernames can't be changed.
- Production also has a second admin, `admin2`, added directly in the database on 2026-10-03 (the Accounts page only creates `user` accounts). Permissions check `role`, never the username, so any number of admins work. The Accounts page won't delete or reset any admin account, so an admin password reset means writing a new hash with SQL.
- Only the admin creates, edits, and deletes accounts.
- Subjects: `code` is the unique ID and can't be changed after creation. Deleting a subject deletes its entries and enrollments, after a warning.
- Users enroll in subjects. They see calendar entries only for the subjects they're enrolled in; the admin sees all entries.
- Entries: type is Cycle Meeting, Task, Exam, or What Happened (an update with no deadline; its details text is required), each with its own gradient. Only Cycle Meetings have a meeting link and an optional end time (after the start time). Each entry has a unique readable ID (for example `E-00042`). Subject code and date are required. Time, meeting link (Meetings only), and instructions are optional.
- Posting entries is off by default for `user` accounts (added 2026-10-04). The admin turns it on per account with the "Can add entries" switch on the Accounts page (`users.entries_allowed`, `accounts.set_entries_permission`); `User.can_post_entries` is always true for admins. Without it a user is read-only: no adding, and no editing or deleting even their own earlier entries (`can_change()` checks it). Their entries stay up.
- Users who may post can add entries only in subjects they're enrolled in, and can edit or delete only their own entries. The admin can edit or delete any entry.
- Every delete needs a reason. Edits need a reason only when the editor didn't create the entry (i.e. the admin editing someone else's).
- Deleting an entry is permanent (changed 2026-10-04; it used to be a soft delete): the row is removed and it disappears for everyone, admin included. Every edit and delete (by anyone) is recorded in `entry_changes`; only the admin sees this change log. Log rows survive the entry: they store its ID and subject code as text (`entry_public_id`, `subject_code`), and `entry_id` becomes NULL (`ON DELETE SET NULL`). A delete row's `details` holds the entry's type and date.
- Deleting a user keeps the entries they created.
- Announcements: only the admin posts or deletes them (no editing; delete and repost). Each one shows on every page for every account, including accounts created later, until that user closes it. Closing is saved per account, so it stays closed on all devices. Every account can still reread all announcements, closed or not, on the Announcements tab. Plain text, line breaks kept.
- Login: 5 wrong passwords in a row lock that account for 5 minutes (`users.failed_logins`, `users.locked_until`); an admin password reset lifts the lock.
- Usage counts use, not logins: a student is active on a day if they loaded any page while logged in (background requests like the calendar feed or closing an announcement count too). "Online now" = active in the last 10 minutes (`ONLINE_WINDOW`); it's an estimate, since saves happen at most every 5 minutes. Counting started when the feature was deployed; earlier use isn't known. Never add polling, heartbeats, timers, cron jobs or auto-refresh for this (or anything else): Neon's free plan bills compute while the database is awake, and pings would keep it awake. Activity is recorded only during requests that happen anyway.

## Repository

- Remote: `origin` → https://github.com/arthurbetezjr/ClassTracker.git, default branch `main`
- Live site: https://classtracker-coral.vercel.app/ (`classtracker.vercel.app` is someone else's project)
- Development happens on Windows (PowerShell).

## Working with the owner

This is the owner's first webapp. Explain what each step does and why, in plain terms, and prefer simple, well-documented tooling over clever setups.
