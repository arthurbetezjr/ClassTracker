import sqlite3

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from classtracker import create_app


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _):
    # SQLite ignores foreign keys unless asked; turn them on so cascades behave like Postgres.
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


@pytest.fixture
def app():
    return create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "test",
        "WTF_CSRF_ENABLED": False,
        "TESTING": True,
        # The real hashing is deliberately slow; a cheap one keeps the test suite fast.
        "PASSWORD_HASH_METHOD": "pbkdf2:sha256:1000",
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


def switch_to_new_user(admin_client, username="juan"):
    """As admin, create a user; then log in as them with their password already changed."""
    admin_client.post("/accounts/", data={"username": username, "password": "startpass1"})
    admin_client.post("/logout")
    login(admin_client, username, "startpass1")
    change_password(admin_client, "startpass1", "userpass1")
    return admin_client


def switch_to_admin(client):
    client.post("/logout")
    login(client, "admin", "adminpass1")
    return client
