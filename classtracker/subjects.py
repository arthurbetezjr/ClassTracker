import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, select

from .auth import admin_required
from .extensions import db
from .models import Entry, Subject, enrollments

CODE_PATTERN = re.compile(r"^[A-Z0-9._-]{1,20}$")

bp = Blueprint("subjects", __name__, url_prefix="/subjects")


def normalize_code(code):
    # Codes are stored uppercase so "cs101" and "CS101" can't both exist.
    return code.strip().upper()


def subjects_with_counts():
    """Every subject with its number of enrolled users and entries, in one query."""
    students = (
        select(enrollments.c.subject_code, func.count().label("n"))
        .group_by(enrollments.c.subject_code)
        .subquery()
    )
    entries = (
        select(Entry.subject_code, func.count().label("n"))
        .group_by(Entry.subject_code)
        .subquery()
    )
    query = (
        select(Subject, func.coalesce(students.c.n, 0), func.coalesce(entries.c.n, 0))
        .outerjoin(students, students.c.subject_code == Subject.code)
        .outerjoin(entries, entries.c.subject_code == Subject.code)
        .order_by(Subject.code)
    )
    return db.session.execute(query).all()


@bp.get("/")
def index():
    if current_user.is_admin:
        return render_template("subjects/admin_index.html", rows=subjects_with_counts())
    subjects = db.session.scalars(select(Subject).order_by(Subject.code)).all()
    enrolled = {subject.code for subject in current_user.subjects}
    return render_template("subjects/user_index.html", subjects=subjects, enrolled=enrolled)


@bp.post("/")
@admin_required
def create():
    code = normalize_code(request.form.get("code", ""))
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    if not CODE_PATTERN.match(code):
        flash("Subject codes must be 1-20 characters: letters, numbers, dots, dashes or underscores (no spaces).", "danger")
    elif db.session.get(Subject, code):
        flash(f"A subject with the code \"{code}\" already exists.", "danger")
    elif not name:
        flash("Please enter a subject name.", "danger")
    else:
        db.session.add(Subject(code=code, name=name[:200], description=description))
        db.session.commit()
        flash(f"Subject \"{code}\" created.", "success")
    return redirect(url_for("subjects.index"))


@bp.route("/<code>/edit", methods=["GET", "POST"])
@admin_required
def edit(code):
    subject = db.get_or_404(Subject, code)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Please enter a subject name.", "danger")
        else:
            subject.name = name[:200]
            subject.description = request.form.get("description", "").strip()
            db.session.commit()
            flash(f"Subject \"{code}\" updated.", "success")
            return redirect(url_for("subjects.index"))
    entry_count = db.session.scalar(select(func.count()).select_from(Entry).filter_by(subject_code=code))
    return render_template("subjects/edit.html", subject=subject, entry_count=entry_count)


@bp.post("/<code>/delete")
@admin_required
def delete(code):
    subject = db.get_or_404(Subject, code)
    db.session.delete(subject)  # the database also removes its entries and enrollments
    db.session.commit()
    flash(f"Subject \"{code}\" deleted, along with its entries and enrollments.", "success")
    return redirect(url_for("subjects.index"))


@bp.post("/<code>/enroll")
def enroll(code):
    if current_user.is_admin:
        abort(403)  # the admin already sees every subject
    subject = db.get_or_404(Subject, code)
    if subject not in current_user.subjects:
        current_user.subjects.append(subject)
        db.session.commit()
    flash(f"You're now tracking {subject.code}: {subject.name}.", "success")
    return redirect(url_for("subjects.index"))


@bp.post("/<code>/unenroll")
def unenroll(code):
    subject = db.get_or_404(Subject, code)
    if subject in current_user.subjects:
        current_user.subjects.remove(subject)
        db.session.commit()
    flash(f"You stopped tracking {subject.code}. Entries you added there stay for others.", "info")
    return redirect(url_for("subjects.index"))
