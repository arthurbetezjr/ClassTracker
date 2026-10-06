"""Usage tracking: which students use ClassTracker, and when.

A student counts as active on a day if they loaded any page while logged in. Activity is saved
during page requests that happen anyway (never by polling, which would keep the free-tier
database awake), and at most every SAVE_INTERVAL per student, using a key in the signed session
cookie, so most page loads cost no database work at all. Admin activity isn't recorded.
"""

import datetime as dt

from flask import Blueprint, current_app, render_template, session
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .auth import admin_required
from .extensions import db
from .models import ROLE_USER, User, UserActivityDay, utcnow
from .timeutil import app_zone, as_utc

ONLINE_WINDOW = dt.timedelta(minutes=10)  # "online now" = active this recently (an estimate)
SAVE_INTERVAL = dt.timedelta(minutes=5)  # must stay shorter than ONLINE_WINDOW
SESSION_KEY = "ct_seen"  # {"u": user id, "t": UTC ISO time of the last save}

bp = Blueprint("usage", __name__, url_prefix="/usage")


@bp.before_request
@admin_required
def only_admins():
    pass


@bp.get("/")
def index():
    return render_template("usage/index.html", **usage_stats(utcnow()),
                           online_minutes=int(ONLINE_WINDOW.total_seconds() // 60))


def usage_stats(now):
    """Everything the Usage page shows, computed from the activity rows (nothing is stored)."""
    today = local_day(now)

    def students_active_since(first_day):
        return db.session.scalar(
            select(func.count(func.distinct(UserActivityDay.user_id)))
            .join(User, User.id == UserActivityDay.user_id)
            .where(User.role == ROLE_USER, UserActivityDay.day >= first_day)
        )

    last_seen = db.session.execute(
        select(User.username, func.max(UserActivityDay.last_seen_at))
        .outerjoin(UserActivityDay, UserActivityDay.user_id == User.id)
        .where(User.role == ROLE_USER)
        .group_by(User.id, User.username)
    ).all()
    # Most recent first, students never seen last, then by username.
    students = sorted(
        ((name, as_utc(seen) if seen else None) for name, seen in last_seen),
        key=lambda row: (row[1] is None, -row[1].timestamp() if row[1] else 0, row[0]),
    )
    online = [name for name, seen in students if seen and seen >= now - ONLINE_WINDOW]
    return {
        "online": online,
        "today": students_active_since(today),
        "this_month": students_active_since(today.replace(day=1)),
        "this_year": students_active_since(today.replace(month=1, day=1)),
        "students": students,
        "counting_started": db.session.scalar(select(func.min(UserActivityDay.day))),
    }


def local_day(moment):
    return as_utc(moment).astimezone(app_zone()).date()


def record_activity(user, now=None):
    """Called before every logged-in request. Saves today's "last seen" row unless the session
    shows it was saved for this user less than SAVE_INTERVAL ago, on the same local day."""
    if user.is_admin:
        return
    now = now or utcnow()
    today = local_day(now)
    if not _save_due(session.get(SESSION_KEY), user.id, now, today):
        return
    try:
        _save(user.id, today, now)
    except SQLAlchemyError:
        # Recording usage must never break a page.
        db.session.rollback()
        current_app.logger.warning("Could not record activity for user %s", user.id, exc_info=True)
        return
    session[SESSION_KEY] = {"u": user.id, "t": now.isoformat()}


def _save_due(seen, user_id, now, today):
    try:
        if seen["u"] != user_id:
            return True
        last = as_utc(dt.datetime.fromisoformat(seen["t"]))
    except (TypeError, KeyError, ValueError):
        return True  # no key yet, or one we can't read
    # A time in the future can't be trusted, so it counts as stale too.
    return not dt.timedelta(0) <= now - last < SAVE_INTERVAL or local_day(last) < today


def _save(user_id, day, now):
    # Update today's row, or insert it. Plain UPDATE/INSERT works on both SQLite and Postgres;
    # if another request inserted the same row a moment ago, the INSERT fails and we update instead.
    if not _update_row(user_id, day, now):
        try:
            db.session.execute(insert(UserActivityDay).values(user_id=user_id, day=day, last_seen_at=now))
            db.session.commit()
            return
        except IntegrityError:
            db.session.rollback()
            _update_row(user_id, day, now)
    db.session.commit()


def _update_row(user_id, day, now):
    result = db.session.execute(
        update(UserActivityDay)
        .where(UserActivityDay.user_id == user_id, UserActivityDay.day == day)
        .values(last_seen_at=now)
    )
    return result.rowcount
