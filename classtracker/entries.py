import datetime as dt
import re

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .auth import admin_required
from .extensions import db
from .models import ENTRY_COLORS, ENTRY_TYPES, Entry, EntryChange, Subject, enrollments
from .timeutil import local_today, nice_date, nice_time

bp = Blueprint("entries", __name__, url_prefix="/entries")

URL_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
FIELD_LABELS = {
    "type": "Type",
    "subject_code": "Subject",
    "date": "Date",
    "time": "Time",
    "end_time": "End time",
    "meeting_link": "Meeting link",
    "instructions": "Instructions",
}


# --- Who can see and change what -------------------------------------------------------------

def visible_entries():
    """Query for the entries the current user may see: all for the admin, enrolled subjects otherwise."""
    query = select(Entry).options(joinedload(Entry.subject), joinedload(Entry.created_by))
    if not current_user.is_admin:
        enrolled = select(enrollments.c.subject_code).where(enrollments.c.user_id == current_user.id)
        query = query.where(Entry.subject_code.in_(enrolled))
    return query


def allowed_subjects():
    """Subjects the current user may add entries to."""
    if current_user.is_admin:
        return db.session.scalars(select(Subject).order_by(Subject.code)).all()
    return sorted(current_user.subjects, key=lambda subject: subject.code)


def get_visible_entry(entry_id):
    entry = db.session.scalar(visible_entries().where(Entry.id == entry_id))
    if entry is None:
        abort(404)
    return entry


def can_change(entry):
    """Users change only their own entries, and only while the admin allows them to post entries;
    the admin can change any."""
    if not current_user.can_post_entries:
        return False
    return current_user.is_admin or entry.created_by_id == current_user.id


def edit_needs_reason(entry):
    # The admin must explain edits to other people's entries.
    return entry.created_by_id != current_user.id


# --- Form handling ----------------------------------------------------------------------------

def read_form():
    form = request.form
    return {name: form.get(name, "").strip() for name in (*FIELD_LABELS, "reason")}


def clean(values):
    """Validate submitted values. Returns (fields for the Entry, error message or None)."""
    if values["type"] not in ENTRY_TYPES:
        return None, "Choose an entry type."
    if values["subject_code"] not in {subject.code for subject in allowed_subjects()}:
        return None, "Choose one of your subjects."
    try:
        date = dt.date.fromisoformat(values["date"])
    except ValueError:
        return None, "Choose a date."
    try:
        time = dt.time.fromisoformat(values["time"]) if values["time"] else None
        end_time = dt.time.fromisoformat(values["end_time"]) if values["end_time"] else None
    except ValueError:
        return None, "Enter a valid time."
    is_meeting = values["type"] == "meeting"
    if not is_meeting:
        end_time = None
    elif end_time and not time:
        return None, "Add a start time too, or clear the end time."
    elif end_time and end_time <= time:
        return None, "The end time must be after the start time."
    if values["type"] == "happened" and not values["instructions"]:
        return None, "Describe what happened."
    link = values["meeting_link"] if is_meeting else ""
    if link:
        if not URL_SCHEME.match(link):
            link = "https://" + link
        elif not link.lower().startswith(("http://", "https://")):
            return None, "Meeting links must start with http:// or https://."
        if len(link) > 500:
            return None, "The meeting link is too long."
    fields = {
        "type": values["type"],
        "subject_code": values["subject_code"],
        "date": date,
        "time": time,
        "end_time": end_time,
        "meeting_link": link,
        "instructions": values["instructions"],
    }
    return fields, None


def form_values(entry):
    """An entry's fields as the strings the form inputs expect."""
    return {
        "type": entry.type,
        "subject_code": entry.subject_code,
        "date": entry.date.isoformat(),
        "time": entry.time.strftime("%H:%M") if entry.time else "",
        "end_time": entry.end_time.strftime("%H:%M") if entry.end_time else "",
        "meeting_link": entry.meeting_link,
        "instructions": entry.instructions,
        "reason": "",
    }


def log_change(entry, action, reason, details=""):
    # The log keeps the entry's ID and subject as text, so the record outlives a deleted entry.
    db.session.add(EntryChange(entry_id=entry.id, entry_public_id=entry.public_id, subject_code=entry.subject_code,
                               action=action, reason=reason, details=details, actor_id=current_user.id))


def describe(field, value):
    if value in (None, ""):
        return "(blank)"
    if field == "type":
        return ENTRY_TYPES[value]
    if field == "date":
        return nice_date(value)
    if field in ("time", "end_time"):
        return nice_time(value)
    return str(value)


def describe_changes(entry, fields):
    """Human-readable list of what an edit changes, e.g. "Date: Mon, Oct 5, 2026 → Tue, Oct 6, 2026"."""
    changes = []
    for field, new in fields.items():
        old = getattr(entry, field)
        if old == new:
            continue
        if field == "instructions":
            changes.append("Instructions / details changed")
        else:
            changes.append(f"{FIELD_LABELS[field]}: {describe(field, old)} → {describe(field, new)}")
    return changes


# --- Views -------------------------------------------------------------------------------------

@bp.get("/")
def index():
    subject = request.args.get("subject", "")
    entry_type = request.args.get("type", "")
    when = request.args.get("when", "upcoming")

    query = visible_entries()
    if subject:
        query = query.where(Entry.subject_code == subject)
    if entry_type in ENTRY_TYPES:
        query = query.where(Entry.type == entry_type)
    today = local_today()
    if when == "past":
        query = query.where(Entry.date < today).order_by(Entry.date.desc(), Entry.time.desc())
    elif when == "all":
        query = query.order_by(Entry.date.desc(), Entry.time.desc())
    else:
        when = "upcoming"
        query = query.where(Entry.date >= today).order_by(Entry.date, Entry.time)

    return render_template(
        "entries/index.html",
        entries=db.session.scalars(query).all(),
        subjects=allowed_subjects(),
        filters={"subject": subject, "type": entry_type, "when": when},
    )


@bp.route("/new", methods=["GET", "POST"])
def new():
    if not current_user.can_post_entries:
        flash("Your account can't add entries yet. Ask the admin if you need to.", "warning")
        return redirect(url_for("home"))
    subjects = allowed_subjects()
    if not subjects:
        flash("Enroll in a subject first; then you can add entries to it." if not current_user.is_admin
              else "Create a subject first; entries belong to a subject.", "warning")
        return redirect(url_for("subjects.index"))

    values = {"type": request.args.get("type", "meeting"), "subject_code": request.args.get("subject", ""),
              "date": request.args.get("date") or local_today().isoformat(),
              "time": "", "end_time": "", "meeting_link": "", "instructions": "", "reason": ""}
    if request.method == "POST":
        values = read_form()
        fields, error = clean(values)
        if error:
            flash(error, "danger")
        else:
            entry = Entry(**fields, created_by_id=current_user.id)
            db.session.add(entry)
            db.session.commit()
            flash(f"{ENTRY_TYPES[entry.type]} {entry.public_id} added.", "success")
            return redirect(url_for("entries.detail", entry_id=entry.id))
    return render_template("entries/form.html", entry=None, values=values, subjects=subjects, needs_reason=False)


@bp.get("/<int:entry_id>")
def detail(entry_id):
    entry = get_visible_entry(entry_id)
    return render_template("entries/detail.html", entry=entry, can_change=can_change(entry))


@bp.route("/<int:entry_id>/edit", methods=["GET", "POST"])
def edit(entry_id):
    entry = get_visible_entry(entry_id)
    if not can_change(entry):
        abort(403)
    needs_reason = edit_needs_reason(entry)
    values = form_values(entry)
    if request.method == "POST":
        values = read_form()
        fields, error = clean(values)
        changes = describe_changes(entry, fields) if fields else []
        if error:
            flash(error, "danger")
        elif not changes:
            flash("Nothing was changed.", "info")
            return redirect(url_for("entries.detail", entry_id=entry.id))
        elif needs_reason and not values["reason"]:
            flash("Please give a reason for editing someone else's entry.", "danger")
        else:
            for field, value in fields.items():
                setattr(entry, field, value)
            log_change(entry, "edit", values["reason"], "\n".join(changes))
            db.session.commit()
            flash(f"{entry.public_id} updated.", "success")
            return redirect(url_for("entries.detail", entry_id=entry.id))
    return render_template("entries/form.html", entry=entry, values=values,
                           subjects=allowed_subjects(), needs_reason=needs_reason)


@bp.post("/<int:entry_id>/delete")
def delete(entry_id):
    entry = get_visible_entry(entry_id)
    if not can_change(entry):
        abort(403)
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("Please give a reason for deleting.", "danger")
        return redirect(url_for("entries.detail", entry_id=entry.id))
    # Deleting is permanent: the entry is removed for everyone. Only the change log remembers it.
    log_change(entry, "delete", reason, f"{ENTRY_TYPES[entry.type]} on {nice_date(entry.date)}")
    db.session.flush()
    db.session.delete(entry)  # the database keeps the log rows, with their entry link set to NULL
    db.session.commit()
    flash(f"{entry.public_id} deleted.", "success")
    return redirect(url_for("home"))


def at(date, time):
    """ISO date, or date and time, in the form FullCalendar expects."""
    return f"{date.isoformat()}T{time.strftime('%H:%M')}" if time else date.isoformat()


@bp.get("/calendar-feed")
def calendar_feed():
    """Entries between ?start and ?end as FullCalendar events (JSON), limited to what the user may see."""
    try:
        # FullCalendar sends e.g. "2026-09-28T00:00:00+08:00"; only the date part matters.
        start = dt.date.fromisoformat(request.args["start"][:10])
        end = dt.date.fromisoformat(request.args["end"][:10])
    except (KeyError, ValueError):
        abort(400)
    query = visible_entries().where(Entry.date >= start, Entry.date < end).order_by(Entry.date, Entry.time)
    if subject := request.args.get("subject"):
        query = query.where(Entry.subject_code == subject)
    if "types" in request.args:  # present but empty means every type is switched off
        query = query.where(Entry.type.in_([t for t in request.args["types"].split(",") if t in ENTRY_TYPES]))

    events = []
    for entry in db.session.scalars(query):
        events.append({
            "id": entry.id,
            "title": f"{entry.subject_code} · {ENTRY_TYPES[entry.type]}",
            "start": at(entry.date, entry.time),
            "end": at(entry.date, entry.end_time) if entry.end_time else None,
            "allDay": entry.time is None,
            "color": ENTRY_COLORS[entry.type],
            "url": url_for("entries.detail", entry_id=entry.id),
            "classNames": [f"ct-type-{entry.type}"],
            "extendedProps": {
                "publicId": entry.public_id,
                "subjectCode": entry.subject_code,
                "subjectName": entry.subject.name,
            },
        })
    return jsonify(events)


@bp.get("/log")
@admin_required
def log():
    changes = db.session.scalars(
        select(EntryChange)
        .options(joinedload(EntryChange.actor))
        .order_by(EntryChange.created_at.desc(), EntryChange.id.desc())
        .limit(300)
    ).all()
    return render_template("entries/log.html", changes=changes)
