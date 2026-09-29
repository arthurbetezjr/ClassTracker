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


def login(client, username="admin", password="12345"):
    return client.post("/login", data={"username": username, "password": password})


def change_password(client, current, new, confirm=None):
    return client.post("/account", data={
        "current_password": current,
        "new_password": new,
        "confirm_password": new if confirm is None else confirm,
    })
