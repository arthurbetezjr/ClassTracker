import pytest
from conftest import login, switch_to_admin, switch_to_new_user

from classtracker.extensions import db
from classtracker.models import Entry, User

ENTRY = {"type": "task", "subject_code": "CS101", "date": "2026-10-05", "time": "", "end_time": "",
         "meeting_link": "", "instructions": "Read chapter 1"}


def get_user(app, username):
    with app.app_context():
        return db.session.query(User).filter_by(username=username).one()


def entry_count(app):
    with app.app_context():
        return db.session.query(Entry).count()


def set_permission(client, app, username, allowed):
    user_id = get_user(app, username).id
    return client.post(f"/accounts/{user_id}/entries-permission", data={"allowed": "1"} if allowed else {},
                       follow_redirects=True)


def as_user(client, username):
    client.post("/logout")
    login(client, username, "userpass1")
    return client


@pytest.fixture
def setup(admin_client):
    """Subject CS101 with user "juan" enrolled but NOT allowed to post entries; logged in as admin at the end."""
    admin_client.post("/subjects/", data={"code": "CS101", "name": "Programming"})
    switch_to_new_user(admin_client, "juan", allow_entries=False)
    admin_client.post("/subjects/CS101/enroll")
    switch_to_admin(admin_client)
    return admin_client


def test_new_accounts_cannot_post_entries(app, admin_client):
    admin_client.post("/accounts/", data={"username": "maria", "password": "startpass1"})
    admin_client.post("/accounts/bulk", data={"usernames": "pedro\nana", "password": "startpass1"})
    for username in ("maria", "pedro", "ana"):
        assert not get_user(app, username).entries_allowed


def test_user_without_permission_cannot_add_entries(app, setup):
    client = as_user(setup, "juan")
    response = client.get("/entries/new")
    assert response.status_code == 302 and response.headers["Location"].endswith("/")
    client.post("/entries/new", data=ENTRY)
    assert entry_count(app) == 0

    calendar = client.get("/").data
    assert b"Add entry" not in calendar and b"var canAdd = false" in calendar
    assert b"Add entry" not in client.get("/entries/").data


def test_admin_allows_user_to_post(app, setup):
    assert b"can now add" in set_permission(setup, app, "juan", True).data
    assert get_user(app, "juan").entries_allowed

    client = as_user(setup, "juan")
    assert b"Add entry" in client.get("/").data
    client.post("/entries/new", data=ENTRY)
    assert entry_count(app) == 1


def test_revoked_user_keeps_entries_but_cannot_change_them(app, setup):
    set_permission(setup, app, "juan", True)
    client = as_user(setup, "juan")
    client.post("/entries/new", data=ENTRY)
    with app.app_context():
        entry_id = db.session.query(Entry.id).scalar()

    switch_to_admin(client)
    assert b"can no longer" in set_permission(client, app, "juan", False).data

    as_user(client, "juan")
    assert b"Read chapter 1" in client.get(f"/entries/{entry_id}").data  # still visible
    assert b"Edit</a>" not in client.get(f"/entries/{entry_id}").data
    assert client.get(f"/entries/{entry_id}/edit").status_code == 403
    assert client.post(f"/entries/{entry_id}/delete", data={"reason": "oops"}).status_code == 403
    with app.app_context():
        assert db.session.get(Entry, entry_id) is not None


def test_only_admins_change_permissions(app, setup):
    client = as_user(setup, "juan")
    user_id = get_user(app, "juan").id
    assert client.post(f"/accounts/{user_id}/entries-permission", data={"allowed": "1"}).status_code == 403
    assert not get_user(app, "juan").entries_allowed


def test_admins_always_post_entries(app, setup):
    admin_id = get_user(app, "admin").id
    setup.post(f"/accounts/{admin_id}/entries-permission", data={})
    assert b"always" in setup.get("/accounts/").data
    setup.post("/entries/new", data=ENTRY)
    assert entry_count(app) == 1
