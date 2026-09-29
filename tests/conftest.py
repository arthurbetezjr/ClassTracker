import pytest

from classtracker import create_app


@pytest.fixture
def app():
    return create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "test",
        "WTF_CSRF_ENABLED": False,
        "TESTING": True,
    })


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(client):
    """A client logged in as the admin, past the first-login password change."""
    login(client)
    change_password(client, "12345", "adminpass1")
    return client


def login(client, username="admin", password="12345"):
    return client.post("/login", data={"username": username, "password": password})


def change_password(client, current, new, confirm=None):
    return client.post("/account", data={
        "current_password": current,
        "new_password": new,
        "confirm_password": new if confirm is None else confirm,
    })
