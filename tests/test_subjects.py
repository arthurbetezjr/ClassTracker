import datetime as dt

from conftest import switch_to_admin, switch_to_new_user

from classtracker.extensions import db
from classtracker.models import Entry, Subject, User, enrollments


def create_subject(client, code="cs101", name="Intro to Programming", description=""):
    return client.post("/subjects/", data={"code": code, "name": name, "description": description},
                       follow_redirects=True)


def test_admin_creates_subject_with_uppercase_code(app, admin_client):
    assert b"created" in create_subject(admin_client, "cs101", description="Basics").data
    with app.app_context():
        subject = db.session.get(Subject, "CS101")
        assert subject.name == "Intro to Programming" and subject.description == "Basics"
    assert b"CS101" in admin_client.get("/subjects/").data


def test_create_subject_validation(admin_client):
    create_subject(admin_client, "CS101")
    assert b"already exists" in create_subject(admin_client, "cs101").data
    assert b"no spaces" in create_subject(admin_client, "CS 101").data
    assert b"enter a subject name" in create_subject(admin_client, "CS102", name="  ").data


def test_edit_changes_name_and_description_but_not_code(app, admin_client):
    create_subject(admin_client)
    admin_client.post("/subjects/CS101/edit", data={"name": "Programming 1", "description": "New", "code": "HACK"})
    with app.app_context():
        subject = db.session.get(Subject, "CS101")
        assert (subject.name, subject.description) == ("Programming 1", "New")
        assert db.session.get(Subject, "HACK") is None


def test_delete_subject_removes_entries_and_enrollments(app, admin_client):
    create_subject(admin_client)
    switch_to_new_user(admin_client)
    admin_client.post("/subjects/CS101/enroll")
    with app.app_context():
        db.session.add(Entry(type="exam", subject_code="CS101", date=dt.date(2026, 10, 5)))
        db.session.commit()

    switch_to_admin(admin_client)
    assert b"<strong>1</strong> entry" in admin_client.get("/subjects/CS101/edit").data
    admin_client.post("/subjects/CS101/delete")
    with app.app_context():
        assert db.session.get(Subject, "CS101") is None
        assert db.session.query(Entry).count() == 0
        assert db.session.query(enrollments).count() == 0
        assert db.session.query(User).filter_by(username="juan").one()  # the user is untouched


def test_user_enrolls_and_unenrolls(app, admin_client):
    create_subject(admin_client)
    switch_to_new_user(admin_client)
    page = admin_client.get("/subjects/").data
    assert b"CS101" in page and b"Enroll</button>" in page

    admin_client.post("/subjects/CS101/enroll")
    admin_client.post("/subjects/CS101/enroll")  # enrolling twice is harmless
    with app.app_context():
        user = db.session.query(User).filter_by(username="juan").one()
        assert [s.code for s in user.subjects] == ["CS101"]
    assert b"Unenroll</button>" in admin_client.get("/subjects/").data

    admin_client.post("/subjects/CS101/unenroll")
    with app.app_context():
        assert db.session.query(User).filter_by(username="juan").one().subjects == []


def test_user_cannot_manage_subjects(app, admin_client):
    create_subject(admin_client)
    switch_to_new_user(admin_client)
    assert admin_client.post("/subjects/", data={"code": "X1", "name": "X"}).status_code == 403
    assert admin_client.get("/subjects/CS101/edit").status_code == 403
    assert admin_client.post("/subjects/CS101/delete").status_code == 403
    with app.app_context():
        assert db.session.get(Subject, "CS101") is not None
        assert db.session.get(Subject, "X1") is None


def test_unknown_subject_is_404(admin_client):
    assert admin_client.get("/subjects/NOPE/edit").status_code == 404
