from conftest import change_password, login


def test_anonymous_visitor_is_sent_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_wrong_password_is_rejected(client):
    response = login(client, password="wrong")
    assert b"Wrong password" in response.data


def test_unknown_username_is_reported(client):
    response = login(client, username="nobody")
    assert b"no account with the username" in response.data
    assert b"nobody" in response.data


def test_default_admin_must_change_password_first(client):
    login(client)
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/account")


def test_password_change_rules(client):
    login(client)
    assert b"at least 8" in change_password(client, "12345", "short").data
    assert b"match" in change_password(client, "12345", "longenough1", "longenough2").data
    assert b"current password is wrong" in change_password(client, "nope", "longenough1").data


def test_password_change_unlocks_app_and_replaces_old_password(client):
    login(client)
    response = change_password(client, "12345", "newpassword1")
    assert response.headers["Location"].endswith("/")
    assert client.get("/").status_code == 200

    client.post("/logout")
    assert b"Wrong password" in login(client, password="12345").data
    assert login(client, password="newpassword1").status_code == 302
    assert client.get("/").status_code == 200


def test_logout_ends_session(client):
    login(client)
    change_password(client, "12345", "newpassword1")
    client.post("/logout")
    assert client.get("/").status_code == 302
