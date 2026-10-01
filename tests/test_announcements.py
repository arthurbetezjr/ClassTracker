from conftest import switch_to_admin, switch_to_new_user

from classtracker.extensions import db
from classtracker.models import Announcement


def post(client, body="Exams moved to Friday", title="Heads up"):
    return client.post("/announcements/", data={"title": title, "body": body}, follow_redirects=True)


def announcement_id(app):
    with app.app_context():
        return db.session.query(Announcement).one().id


def test_admin_posts_and_users_see_card(app, admin_client):
    assert b"Announcement posted" in post(admin_client).data
    switch_to_new_user(admin_client)
    page = admin_client.get("/subjects/").data
    assert b"Exams moved to Friday" in page and b"Heads up" in page


def test_message_is_required(app, admin_client):
    assert b"Write the announcement message" in post(admin_client, body="   ").data
    with app.app_context():
        assert db.session.query(Announcement).count() == 0


def test_only_admin_manages_announcements(app, admin_client):
    post(admin_client)
    switch_to_new_user(admin_client)
    assert admin_client.get("/announcements/").status_code == 403
    assert admin_client.post("/announcements/", data={"body": "hi"}).status_code == 403
    assert admin_client.post(f"/announcements/{announcement_id(app)}/delete").status_code == 403


def test_closing_hides_it_only_for_that_user(app, admin_client):
    post(admin_client)
    an_id = announcement_id(app)
    switch_to_new_user(admin_client, "juan")
    response = admin_client.post(f"/announcements/{an_id}/dismiss", headers={"X-Requested-With": "fetch"})
    assert response.status_code == 204
    admin_client.post(f"/announcements/{an_id}/dismiss")  # closing twice is harmless
    assert b"Exams moved to Friday" not in admin_client.get("/").data

    switch_to_admin(admin_client)
    switch_to_new_user(admin_client, "maria")  # accounts created later still see it
    assert b"Exams moved to Friday" in admin_client.get("/").data


def test_delete_removes_it_for_everyone(app, admin_client):
    post(admin_client)
    an_id = announcement_id(app)
    switch_to_new_user(admin_client)
    admin_client.post(f"/announcements/{an_id}/dismiss")
    switch_to_admin(admin_client)
    assert b"Announcement deleted" in admin_client.post(f"/announcements/{an_id}/delete", follow_redirects=True).data
    switch_to_new_user(admin_client, "maria")
    assert b"Exams moved to Friday" not in admin_client.get("/").data


def test_text_is_escaped(admin_client):
    page = post(admin_client, body="<script>alert(1)</script>").data
    assert b"<script>alert(1)" not in page and b"&lt;script&gt;" in page
