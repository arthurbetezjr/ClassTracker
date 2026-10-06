import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from conftest import switch_to_new_user
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import SQLAlchemyError

from classtracker import usage
from classtracker.extensions import db
from classtracker.models import User, UserActivityDay
from classtracker.timeutil import as_utc

MANILA = ZoneInfo("Asia/Manila")


def manila(year, month, day, hour=12, minute=0):
    """A Manila wall-clock time, as the UTC moment the app stores."""
    return dt.datetime(year, month, day, hour, minute, tzinfo=MANILA).astimezone(dt.timezone.utc)


@pytest.fixture
def clock(monkeypatch):
    """Controls what time record_activity thinks it is."""
    class Clock:
        now = manila(2026, 10, 6, 9, 0)

    monkeypatch.setattr(usage, "utcnow", lambda: Clock.now)
    return Clock


def user_id(app, username):
    with app.app_context():
        return db.session.scalar(select(User.id).filter_by(username=username))


def activity(app, username="juan"):
    """The user's activity rows as (day, last_seen_at in UTC), oldest day first."""
    with app.app_context():
        rows = db.session.execute(
            select(UserActivityDay.day, UserActivityDay.last_seen_at)
            .where(UserActivityDay.user_id == user_id(app, username))
            .order_by(UserActivityDay.day)
        ).all()
    return [(day, as_utc(seen)) for day, seen in rows]


def add_activity(app, username, seen_at, day=None):
    with app.app_context():
        day = day or seen_at.astimezone(MANILA).date()
        db.session.execute(insert(UserActivityDay).values(
            user_id=user_id(app, username), day=day, last_seen_at=seen_at))
        db.session.commit()


def fresh_student(app, admin_client, username="juan"):
    """Log in as a new student, then forget the activity recorded while logging in."""
    switch_to_new_user(admin_client, username)
    with app.app_context():
        db.session.execute(delete(UserActivityDay))
        db.session.commit()
    with admin_client.session_transaction() as session:
        session.pop(usage.SESSION_KEY, None)
    return admin_client


# Recording


def test_first_page_load_records_today(app, admin_client, clock):
    client = fresh_student(app, admin_client)
    assert client.get("/").status_code == 200
    assert activity(app) == [(dt.date(2026, 10, 6), clock.now)]
    with client.session_transaction() as session:
        assert session[usage.SESSION_KEY] == {"u": user_id(app, "juan"), "t": clock.now.isoformat()}


def test_reload_within_five_minutes_skips_database(app, admin_client, clock, monkeypatch):
    client = fresh_student(app, admin_client)
    client.get("/")
    first = activity(app)

    saves = []
    monkeypatch.setattr(usage, "_save", lambda *args: saves.append(args))
    clock.now += dt.timedelta(minutes=4, seconds=59)
    assert client.get("/").status_code == 200
    assert saves == []
    assert activity(app) == first


def test_reload_after_five_minutes_updates_same_row(app, admin_client, clock):
    client = fresh_student(app, admin_client)
    client.get("/")
    clock.now += dt.timedelta(minutes=5)
    client.get("/")
    assert activity(app) == [(dt.date(2026, 10, 6), clock.now)]


def test_new_local_day_adds_a_row(app, admin_client, clock):
    client = fresh_student(app, admin_client)
    clock.now = manila(2026, 10, 6, 23, 58)
    client.get("/")
    clock.now = manila(2026, 10, 7, 0, 1)  # only 3 minutes later, but a new day in Manila
    client.get("/")
    assert activity(app) == [
        (dt.date(2026, 10, 6), manila(2026, 10, 6, 23, 58)),
        (dt.date(2026, 10, 7), manila(2026, 10, 7, 0, 1)),
    ]


def test_session_key_from_another_user_is_ignored(app, admin_client, clock):
    client = fresh_student(app, admin_client)
    with client.session_transaction() as session:
        session[usage.SESSION_KEY] = {"u": 999, "t": clock.now.isoformat()}
    client.get("/")
    assert activity(app) == [(dt.date(2026, 10, 6), clock.now)]


def test_existing_row_for_today_is_updated(app, admin_client, clock):
    client = fresh_student(app, admin_client)
    add_activity(app, "juan", clock.now - dt.timedelta(hours=1))
    assert client.get("/").status_code == 200
    assert activity(app) == [(dt.date(2026, 10, 6), clock.now)]


def test_concurrent_insert_falls_back_to_update(app, admin_client, clock, monkeypatch):
    # Another request inserts today's row between our UPDATE (no row yet) and our INSERT.
    client = fresh_student(app, admin_client)
    add_activity(app, "juan", clock.now - dt.timedelta(hours=1))
    real_update = usage._update_row
    calls = []

    def update_missing_the_row_once(*args):
        calls.append(args)
        return 0 if len(calls) == 1 else real_update(*args)

    monkeypatch.setattr(usage, "_update_row", update_missing_the_row_once)
    assert client.get("/").status_code == 200
    assert len(calls) == 2
    assert activity(app) == [(dt.date(2026, 10, 6), clock.now)]


def test_admin_activity_is_not_recorded(app, admin_client, clock):
    admin_client.get("/")
    admin_client.get("/accounts/")
    with app.app_context():
        assert db.session.scalars(select(UserActivityDay)).all() == []
    with admin_client.session_transaction() as session:
        assert usage.SESSION_KEY not in session


def test_database_failure_does_not_break_the_page(app, admin_client, clock, monkeypatch):
    client = fresh_student(app, admin_client)

    def broken_save(*args):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(usage, "_save", broken_save)
    assert client.get("/").status_code == 200
    assert activity(app) == []
    with client.session_transaction() as session:
        assert usage.SESSION_KEY not in session  # so the next page load tries again


# Usage page


def create_students(admin_client, *usernames):
    for username in usernames:
        admin_client.post("/accounts/", data={"username": username, "password": "startpass1"})


def stats(app, now):
    with app.test_request_context():
        return usage.usage_stats(now)


def test_counts_today_month_and_year_in_local_time(app, admin_client):
    now = manila(2026, 10, 6, 9, 0)
    create_students(admin_client, "ana", "ben", "cara", "dino", "ella")
    add_activity(app, "ana", manila(2026, 10, 6, 8, 0))     # today
    add_activity(app, "ana", manila(2026, 9, 10))           # ana counted once per period
    add_activity(app, "ben", manila(2026, 10, 1, 0, 30))    # Oct 1 in Manila, still Sep 30 in UTC
    add_activity(app, "cara", manila(2026, 9, 30, 23, 30))  # last month
    add_activity(app, "dino", manila(2026, 3, 3))           # earlier this year
    add_activity(app, "ella", manila(2025, 12, 31, 23, 59)) # last year

    result = stats(app, now)
    assert (result["today"], result["this_month"], result["this_year"]) == (1, 2, 4)
    assert result["online"] == []
    assert result["counting_started"] == dt.date(2025, 12, 31)


def test_online_now_uses_ten_minute_window(app, admin_client):
    now = manila(2026, 10, 6, 9, 0)
    create_students(admin_client, "ana", "ben", "cara")
    add_activity(app, "ana", now - dt.timedelta(minutes=11))
    add_activity(app, "ben", now - dt.timedelta(minutes=9))
    add_activity(app, "cara", now - dt.timedelta(minutes=2))
    assert stats(app, now)["online"] == ["cara", "ben"]


def test_page_lists_students_by_last_seen(app, admin_client, clock):
    create_students(admin_client, "ana", "ben", "zed", "carl")
    add_activity(app, "ben", clock.now - dt.timedelta(minutes=3))
    add_activity(app, "ana", manila(2026, 10, 2, 14, 30))
    add_activity(app, "ana", manila(2026, 10, 1, 8, 0))

    page = admin_client.get("/usage/").get_data(as_text=True)
    assert "Counting started Oct 1, 2026." in page
    assert "Oct 2, 2026 2:30 PM" in page  # ana's latest row, in Manila time
    assert "Nobody right now." not in page
    # Most recent first, then the never-seen students by username; admins aren't listed.
    table = page[page.index("All students"):]
    positions = [table.index(f"<td>{name}</td>") for name in ("ben", "ana", "carl", "zed")]
    assert positions == sorted(positions)
    assert table.count("Never") == 2
    assert "<td>admin</td>" not in table


def test_page_before_any_activity(admin_client, clock):
    page = admin_client.get("/usage/").get_data(as_text=True)
    assert "No activity recorded yet." in page
    assert "Nobody right now." in page


def test_deleting_a_user_deletes_their_activity(app, admin_client):
    create_students(admin_client, "juan")
    add_activity(app, "juan", manila(2026, 10, 5))
    juan_id = user_id(app, "juan")
    response = admin_client.post(f"/accounts/{juan_id}/delete", follow_redirects=True)
    assert b"deleted" in response.data
    with app.app_context():
        assert db.session.scalars(select(UserActivityDay)).all() == []


def test_usage_page_is_admin_only(app, admin_client):
    assert b">Usage</a>" in admin_client.get("/").data
    assert admin_client.get("/usage/").status_code == 200

    switch_to_new_user(admin_client)
    assert admin_client.get("/usage/").status_code == 403
    assert b">Usage</a>" not in admin_client.get("/").data

    admin_client.post("/logout")
    assert "/login" in admin_client.get("/usage/").headers["Location"]
