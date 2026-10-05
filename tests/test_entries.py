import pytest
from conftest import login, switch_to_admin, switch_to_new_user

from classtracker.extensions import db
from classtracker.models import Entry, EntryChange, User


def add_entry(client, **overrides):
    data = {"type": "meeting", "subject_code": "CS101", "date": "2026-10-05", "time": "14:30", "end_time": "",
            "meeting_link": "https://zoom.us/j/1", "instructions": "Bring notes"}
    data.update(overrides)
    return client.post("/entries/new", data=data, follow_redirects=True)


def only_entry(app):
    with app.app_context():
        entry = db.session.query(Entry).one()
        db.session.expunge(entry)
        return entry


@pytest.fixture
def setup(app, admin_client):
    """Subjects CS101 and MATH1; user "juan" enrolled in CS101 only; logged in as admin at the end."""
    admin_client.post("/subjects/", data={"code": "CS101", "name": "Programming"})
    admin_client.post("/subjects/", data={"code": "MATH1", "name": "Algebra"})
    switch_to_new_user(admin_client, "juan")
    admin_client.post("/subjects/CS101/enroll")
    switch_to_admin(admin_client)
    return admin_client


def as_user(client, username):
    client.post("/logout")
    login(client, username, "userpass1")
    return client


def test_user_adds_entry_in_enrolled_subject_only(app, setup):
    client = as_user(setup, "juan")
    page = add_entry(client).data
    assert b"E-00001" in page and b"Bring notes" in page
    entry = only_entry(app)
    assert entry.type == "meeting" and entry.time.strftime("%H:%M") == "14:30"

    assert b"Choose one of your subjects" in add_entry(client, subject_code="MATH1").data
    with app.app_context():
        assert db.session.query(Entry).count() == 1


def test_admin_adds_entry_in_any_subject(app, setup):
    add_entry(setup, subject_code="MATH1", type="exam")
    assert only_entry(app).subject_code == "MATH1"


def test_entry_page_links_back_to_calendar(app, setup):
    page = add_entry(setup).data
    assert b'href="/">&larr; Back to calendar' in page


def test_required_and_optional_fields(app, setup):
    assert b"Choose a date" in add_entry(setup, date="").data
    add_entry(setup, type="task", time="", meeting_link="https://ignored.example", instructions="")
    entry = only_entry(app)
    assert entry.time is None and entry.meeting_link == "" and entry.instructions == ""


def test_meeting_links_are_made_safe(app, setup):
    assert b"must start with http" in add_entry(setup, meeting_link="javascript:alert(1)").data
    add_entry(setup, meeting_link="meet.google.com/abc")
    assert only_entry(app).meeting_link == "https://meet.google.com/abc"


def test_users_only_see_entries_of_enrolled_subjects(app, setup):
    add_entry(setup, subject_code="CS101", date="2099-01-01")
    add_entry(setup, subject_code="MATH1", date="2099-01-02")
    client = as_user(setup, "juan")
    page = client.get("/entries/").data
    assert b"E-00001" in page and b"E-00002" not in page
    assert client.get("/entries/2").status_code == 404


def test_user_edits_own_entry_without_reason(app, setup):
    client = as_user(setup, "juan")
    add_entry(client)
    client.post("/entries/1/edit", data={"type": "meeting", "subject_code": "CS101", "date": "2026-10-06",
                                         "time": "14:30", "meeting_link": "https://zoom.us/j/1",
                                         "instructions": "Bring notes"})
    assert only_entry(app).date.isoformat() == "2026-10-06"
    with app.app_context():
        change = db.session.query(EntryChange).one()
        assert change.action == "edit" and "Date:" in change.details


def test_user_cannot_edit_or_delete_others_entries(app, setup):
    add_entry(setup)  # added by admin
    client = as_user(setup, "juan")
    assert client.get("/entries/1").status_code == 200
    assert client.get("/entries/1/edit").status_code == 403
    assert client.post("/entries/1/delete", data={"reason": "troll"}).status_code == 403
    assert only_entry(app).id == 1  # still there


def test_admin_edit_of_someone_elses_entry_needs_reason_and_is_logged(app, setup):
    add_entry(as_user(setup, "juan"))
    admin = switch_to_admin(setup)
    edit = {"type": "exam", "subject_code": "CS101", "date": "2026-10-05", "time": "14:30",
            "meeting_link": "", "instructions": "Bring notes"}
    assert b"give a reason" in admin.post("/entries/1/edit", data=edit).data
    assert only_entry(app).type == "meeting"

    admin.post("/entries/1/edit", data={**edit, "reason": "It is actually an exam"})
    assert only_entry(app).type == "exam"
    log = admin.get("/entries/log").data
    assert b"It is actually an exam" in log and b"Cycle Meeting \xe2\x86\x92 Exam" in log


def test_delete_is_permanent_and_kept_in_the_log(app, setup):
    client = as_user(setup, "juan")
    add_entry(client)
    client.post("/entries/1/edit", data={"type": "exam", "subject_code": "CS101", "date": "2026-10-05",
                                         "time": "14:30", "meeting_link": "", "instructions": "Bring notes"})
    assert b"give a reason" in client.post("/entries/1/delete", data={"reason": " "}, follow_redirects=True).data
    response = client.post("/entries/1/delete", data={"reason": "Class cancelled"})
    assert response.status_code == 302 and response.headers["Location"] == "/"
    with app.app_context():
        assert db.session.query(Entry).count() == 0

    # Gone for everyone, admin included.
    assert client.get("/entries/1").status_code == 404
    admin = switch_to_admin(client)
    assert admin.get("/entries/1").status_code == 404
    assert b'href="/entries/1"' not in admin.get("/entries/?when=all").data

    # The change log still has the edit and the delete, without a link to the missing entry.
    with app.app_context():
        changes = db.session.query(EntryChange).order_by(EntryChange.id).all()
        assert [c.action for c in changes] == ["edit", "delete"]
        assert all(c.entry_id is None and c.entry_public_id == "E-00001" and c.subject_code == "CS101"
                   for c in changes)
        assert changes[1].reason == "Class cancelled" and changes[1].details == "Exam on Mon, Oct 5, 2026"
    log = admin.get("/entries/log").data
    assert b"Class cancelled" in log and b"E-00001" in log and b'href="/entries/1"' not in log


def test_change_log_is_admin_only(setup):
    assert setup.get("/entries/log").status_code == 200
    assert as_user(setup, "juan").get("/entries/log").status_code == 403


def test_entries_survive_their_author_being_deleted(app, setup):
    add_entry(as_user(setup, "juan"))
    admin = switch_to_admin(setup)
    with app.app_context():
        juan_id = db.session.query(User).filter_by(username="juan").one().id
    admin.post(f"/accounts/{juan_id}/delete")
    assert only_entry(app).created_by_id is None
    assert b"deleted account" in admin.get("/entries/1").data


def test_add_entry_without_subjects_redirects(admin_client):
    switch_to_new_user(admin_client, "juan")
    response = admin_client.get("/entries/new")
    assert response.status_code == 302 and "/subjects/" in response.headers["Location"]
