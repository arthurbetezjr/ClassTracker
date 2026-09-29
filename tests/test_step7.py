"""What Happened entries, meeting end times, login lockout, and page chrome."""
import datetime as dt

from conftest import login, switch_to_admin
from test_entries import add_entry, as_user, only_entry, setup  # noqa: F401  (setup is a fixture)

from classtracker.extensions import db
from classtracker.models import User


def test_what_happened_entry(app, setup):
    client = as_user(setup, "juan")
    assert b"Describe what happened" in add_entry(client, type="happened", time="", instructions="").data
    page = add_entry(client, type="happened", time="", instructions="Prof moved the exam to Friday").data
    assert b"What Happened" in page and b"Prof moved the exam to Friday" in page
    entry = only_entry(app)
    assert entry.type == "happened" and entry.meeting_link == "" and entry.end_time is None


def test_new_entry_date_defaults_to_today(setup):
    from classtracker.timeutil import local_today
    with setup.application.app_context():
        today = local_today().isoformat()
    assert f'value="{today}"'.encode() in setup.get("/entries/new").data


def test_meeting_end_time(app, setup):
    add_entry(setup, time="14:00", end_time="15:30")
    entry = only_entry(app)
    assert (entry.time, entry.end_time) == (dt.time(14, 0), dt.time(15, 30))
    assert "2:00 PM – 3:30 PM" in setup.get("/entries/1").get_data(as_text=True)


def test_end_time_rules(app, setup):
    assert b"end time must be after" in add_entry(setup, time="14:00", end_time="13:00").data
    assert b"Add a start time" in add_entry(setup, time="", end_time="13:00").data
    add_entry(setup, type="task", time="14:00", end_time="15:00")  # ignored for non-meetings
    assert only_entry(app).end_time is None


def test_end_time_edit_is_logged(app, setup):
    add_entry(setup, time="14:00", end_time="15:00")
    setup.post("/entries/1/edit", data={"type": "meeting", "subject_code": "CS101", "date": "2026-10-05",
                                        "time": "14:00", "end_time": "16:00", "meeting_link": "https://zoom.us/j/1",
                                        "instructions": "Bring notes"})
    assert "End time: 3:00 PM → 4:00 PM" in setup.get("/entries/log").get_data(as_text=True)


def test_repeated_wrong_passwords_lock_the_account(app, client):
    for _ in range(4):
        assert b"Wrong password." in login(client, password="nope").data
    assert b"locked for 5 minutes" in login(client, password="nope").data
    # Even the right password is refused while locked.
    assert b"Try again in 5 minutes" in login(client, password="12345").data
    assert client.get("/").status_code == 302

    with app.app_context():
        admin = db.session.query(User).filter_by(username="admin").one()
        admin.locked_until = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
        db.session.commit()
    login(client, password="12345")
    assert client.get("/").headers["Location"].endswith("/account")  # logged in (password change pending)


def test_successful_login_resets_the_counter(app, client):
    for _ in range(4):
        login(client, password="nope")
    login(client)
    with app.app_context():
        assert db.session.query(User).filter_by(username="admin").one().failed_logins == 0


def test_admin_reset_lifts_a_lock(app, setup):
    client = as_user(setup, "juan")
    client.post("/logout")
    for _ in range(5):
        login(client, "juan", "nope")
    switch_to_admin(client)
    with app.app_context():
        juan = db.session.query(User).filter_by(username="juan").one()
        assert juan.locked_until is not None
        juan_id = juan.id
    client.post(f"/accounts/{juan_id}/reset-password", data={"password": "temporary1"})
    client.post("/logout")
    login(client, "juan", "temporary1")
    assert client.get("/").headers["Location"].endswith("/account")


def test_every_page_has_logo_theme_switch_and_footer(client):
    page = client.get("/login").get_data(as_text=True)
    assert 'aria-label="ClassTracker logo"' in page
    assert 'id="theme-toggle"' in page and 'data-bs-theme="dark"' in page
    assert "Developed by" in page and "Arthur Betez Jr." in page
    assert "Exclusively free for PUP Open University Entrepreneurship students" in page
    assert "image/svg+xml" in page  # favicon
