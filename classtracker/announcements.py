from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import exists, insert, select

from .auth import admin_required
from .extensions import db
from .models import Announcement, announcement_dismissals

MAX_TITLE_LENGTH = 200

bp = Blueprint("announcements", __name__, url_prefix="/announcements")


def open_announcements():
    """Announcements the logged-in user hasn't closed yet, newest first (shown on every page)."""
    dismissed = exists().where(
        announcement_dismissals.c.announcement_id == Announcement.id,
        announcement_dismissals.c.user_id == current_user.id,
    )
    return db.session.scalars(select(Announcement).where(~dismissed).order_by(Announcement.id.desc())).all()


@bp.get("/")
def index():
    # Everyone can read the full list (including ones they closed); only the admin gets the post form.
    announcements = db.session.scalars(select(Announcement).order_by(Announcement.id.desc())).all()
    if current_user.is_admin:
        return render_template("announcements/index.html", announcements=announcements, max_title=MAX_TITLE_LENGTH)
    return render_template("announcements/user_index.html", announcements=announcements)


@bp.post("/")
@admin_required
def create():
    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()
    if not body:
        flash("Write the announcement message.", "danger")
    elif len(title) > MAX_TITLE_LENGTH:
        flash(f"The title can be at most {MAX_TITLE_LENGTH} characters.", "danger")
    else:
        db.session.add(Announcement(title=title, body=body, created_by=current_user))
        db.session.commit()
        flash("Announcement posted. Everyone will see it until they close it.", "success")
    return redirect(url_for("announcements.index"))


@bp.post("/<int:announcement_id>/delete")
@admin_required
def delete(announcement_id):
    announcement = db.get_or_404(Announcement, announcement_id)
    db.session.delete(announcement)
    db.session.commit()
    flash("Announcement deleted. It no longer shows for anyone.", "success")
    return redirect(url_for("announcements.index"))


@bp.post("/<int:announcement_id>/dismiss")
def dismiss(announcement_id):
    # Any logged-in user can close an announcement for themselves.
    db.get_or_404(Announcement, announcement_id)
    already = db.session.scalar(select(exists().where(
        announcement_dismissals.c.announcement_id == announcement_id,
        announcement_dismissals.c.user_id == current_user.id,
    )))
    if not already:
        db.session.execute(insert(announcement_dismissals).values(
            announcement_id=announcement_id, user_id=current_user.id))
        db.session.commit()
    # The x button sends this in the background; without JavaScript, go back to the page.
    if request.headers.get("X-Requested-With") == "fetch":
        return "", 204
    return redirect(request.referrer or url_for("home"))
