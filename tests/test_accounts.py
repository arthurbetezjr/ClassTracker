from conftest import change_password, login

from classtracker.extensions import db
from classtracker.models import User


def create_user(client, username="juan", password="startpass1"):
    return client.post("/accounts/", data={"username": username, "password": password}, follow_redirects=True)


def get_user(app, username):
    with app.app_context():
        return db.session.query(User).filter_by(username=username).one_or_none()


def test_admin_creates_user_who_must_change_password(app, admin_client):
    assert b"created" in create_user(admin_client, "Juan").data
    user = get_user(app, "juan")  # stored lowercase
    assert user.role == "user" and user.must_change_password

    admin_client.post("/logout")
    login(admin_client, "JUAN", "startpass1")  # login ignores case
    assert admin_client.get("/").headers["Location"].endswith("/account")
    change_password(admin_client, "startpass1", "juanspass1")
    assert admin_client.get("/").status_code == 200


def test_create_user_validation(admin_client):
    create_user(admin_client, "juan")
    assert b"already taken" in create_user(admin_client, "juan").data
    assert b"3-50 characters" in create_user(admin_client, "a b").data
    assert b"at least 8" in create_user(admin_client, "maria", "short").data


def test_regular_user_cannot_manage_accounts(admin_client):
    create_user(admin_client)
    admin_client.post("/logout")
    login(admin_client, "juan", "startpass1")
    change_password(admin_client, "startpass1", "juanspass1")
    assert admin_client.get("/accounts/").status_code == 403
    assert admin_client.post("/accounts/", data={"username": "x", "password": "y"}).status_code == 403
    assert b"Accounts</a>" not in admin_client.get("/").data


def test_reset_password_forces_change(app, admin_client):
    create_user(admin_client)
    user_id = get_user(app, "juan").id
    admin_client.post("/logout")
    login(admin_client, "juan", "startpass1")
    change_password(admin_client, "startpass1", "juanspass1")
    admin_client.post("/logout")

    login(admin_client, "admin", "adminpass1")
    admin_client.post(f"/accounts/{user_id}/reset-password", data={"password": "temporary1"})
    admin_client.post("/logout")

    assert b"Wrong username or password" in login(admin_client, "juan", "juanspass1").data
    login(admin_client, "juan", "temporary1")
    assert admin_client.get("/").headers["Location"].endswith("/account")


def test_delete_user(app, admin_client):
    create_user(admin_client)
    user_id = get_user(app, "juan").id
    assert b"Delete account" in admin_client.get(f"/accounts/{user_id}").data
    assert b"deleted" in admin_client.post(f"/accounts/{user_id}/delete", follow_redirects=True).data
    assert get_user(app, "juan") is None


def test_admin_account_is_protected(app, admin_client):
    admin_id = get_user(app, "admin").id
    admin_client.post(f"/accounts/{admin_id}/delete")
    admin_client.post(f"/accounts/{admin_id}/reset-password", data={"password": "hijacked1"})
    admin = get_user(app, "admin")
    assert admin is not None and admin.check_password("adminpass1")
