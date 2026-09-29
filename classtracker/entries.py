import datetime as dt
import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .auth import admin_required
from .extensions import db
from .models import ENTRY_TYPES, Entry, EntryChange, Subject, enrollments, utcnow
from .timeutil import local_today, nice_date, nice_time

bp = Blueprint("entries", __name__, url_prefix="/entries")

URL_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
FIELD_LABELS = {
    "type": "Type",
    "subject_code": "Subject",
    "date": "Date",
    "time": "Time",
    "meeting_link": "Meeting link",
    "instructions": "Instructions",
}


# --- Who can see and change what -------------------------------------------------------------

def visible_entries():
    """Query for the entries the current user may see: all for the admin, enrolled subjects otherwise."""
    query = select(Entry).options(
        joinedload(Entry.subject), joinedload(Entry.created_by), joinedload(Entry.deleted_by)
    )
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
    """Users change only their own entries; the admin can change any. Deleted entries are final."""
    if entry.deleted_at is not None:
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
    time = None
    if values["time"]:
        try:
            time = dt.time.fromisoformat(values["time"])
        except ValueError:
            return None, "Enter a valid time."
    link = values["meeting_link"] if values["type"] == "meeting" else ""
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
        "meeting_link": entry.meeting_link,
        "instructions": entry.instructions,
        "reason": "",
    }


def describe(field, value):
    if value in (None, ""):
        return "(blank)"
    if field == "type":
        return ENTRY_TYPES[value]
    if field == "date":
        return nice_date(value)
    if field == "time":
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
            changes.append("Instructions changed")
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
    subjects = allowed_subjects()
    if not subjects:
        flash("Enroll in a subject first; then you can add entries to it." if not current_user.is_admin
              else "Create a subject first; entries belong to a subject.", "warning")
        return redirect(url_for("subjects.index"))

    values = {"type": "meeting", "subject_code": request.args.get("subject", ""), "date": request.args.get("date", ""),
              "time": "", "meeting_link": "", "instructions": "", "reason": ""}
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
            db.session.add(EntryChange(entry_id=entry.id, action="edit", reason=values["reason"],
                                       details="\n".join(changes), actor_id=current_user.id))
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
        flash("Please give a reason for deleting. Everyone in the subject will see it.", "danger")
        return redirect(url_for("entries.detail", entry_id=entry.id))
    entry.deleted_at = utcnow()
    entry.deleted_by_id = current_user.id
    entry.delete_reason = reason
    db.session.add(EntryChange(entry_id=entry.id, action="delete", reason=reason, actor_id=current_user.id))
    db.session.commit()
    flash(f"{entry.public_id} deleted. It stays visible, marked as deleted, with your reason.", "success")
    return redirect(url_for("entries.detail", entry_id=entry.id))


@bp.get("/log")
@admin_required
def log():
    changes = db.session.scalars(
        select(EntryChange)
        .options(joinedload(EntryChange.entry).joinedload(Entry.subject), joinedload(EntryChange.actor))
        .order_by(EntryChange.created_at.desc(), EntryChange.id.desc())
        .limit(300)
    ).all()
    return render_template("entries/log.html", changes=changes)
