"""Dates and times in the app's timezone (APP_TIMEZONE), used for "today" and for displaying timestamps."""

import datetime as dt
from zoneinfo import ZoneInfo

from flask import current_app


def app_zone():
    return ZoneInfo(current_app.config["APP_TIMEZONE"])


def local_today():
    return dt.datetime.now(app_zone()).date()


def as_utc(value):
    """Stored timestamps are UTC, but SQLite hands them back without a timezone."""
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value


def local_timestamp(value):
    """Format a stored UTC timestamp in the app's timezone, e.g. "Oct 5, 2026 2:30 PM"."""
    local = as_utc(value).astimezone(app_zone())
    return f"{nice_date(local.date(), weekday=False)} {nice_time(local.time())}"


def nice_date(value, weekday=True):
    """E.g. "Mon, Oct 5, 2026" (built by hand because %-d doesn't work on Windows)."""
    text = f"{value:%b} {value.day}, {value.year}"
    return f"{value:%a}, {text}" if weekday else text


def nice_time(value):
    """E.g. "2:30 PM"."""
    return f"{value.hour % 12 or 12}:{value:%M} {'AM' if value.hour < 12 else 'PM'}"
