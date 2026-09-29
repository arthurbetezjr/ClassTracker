import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from .auth import MIN_PASSWORD_LENGTH, admin_required, normalize_username
from .extensions import db
from .models import ROLE_ADMIN, User

USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,50}$")

bp = Blueprint("accounts", __name__, url_prefix="/accounts")


@bp.before_request
@admin_required
def only_admins():
    pass


@bp.get("/")
def index():
    users = db.session.scalars(select(User).order_by(User.role, User.username)).all()
    return render_template("accounts/index.html", users=users, min_length=MIN_PASSWORD_LENGTH)


@bp.post("/")
def create():
    username = normalize_username(request.form.get("username", ""))
    password = request.form.get("password", "")
    if not USERNAME_PATTERN.match(username):
        flash("Usernames must be 3-50 characters: letters, numbers, dots, dashes or underscores.", "danger")
    elif db.session.scalar(select(User).filter_by(username=username)):
        flash(f"The username \"{username}\" is already taken.", "danger")
    elif len(password) < MIN_PASSWORD_LENGTH:
        flash(f"The starting password must be at least {MIN_PASSWORD_LENGTH} characters.", "danger")
    else:
        user = User(username=username, must_change_password=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(f"Account \"{username}\" created. They'll choose a new password when they first log in.", "success")
    return redirect(url_for("accounts.index"))


@bp.get("/<int:user_id>")
def edit(user_id):
    user = db.get_or_404(User, user_id)
    return render_template("accounts/edit.html", user=user, min_length=MIN_PASSWORD_LENGTH)


@bp.post("/<int:user_id>/reset-password")
def reset_password(user_id):
    user = db.get_or_404(User, user_id)
    if user.role == ROLE_ADMIN:
        flash("Change the admin password in Account settings instead.", "warning")
        return redirect(url_for("accounts.edit", user_id=user.id))
    password = request.form.get("password", "")
    if len(password) < MIN_PASSWORD_LENGTH:
        flash(f"The new password must be at least {MIN_PASSWORD_LENGTH} characters.", "danger")
        return redirect(url_for("accounts.edit", user_id=user.id))
    user.set_password(password)
    user.must_change_password = True
    user.failed_logins = 0
    user.locked_until = None  # a reset also lifts a wrong-password lock
    db.session.commit()
    flash(f"Password for \"{user.username}\" reset. They'll choose a new one at their next login.", "success")
    return redirect(url_for("accounts.index"))


@bp.post("/<int:user_id>/delete")
def delete(user_id):
    user = db.get_or_404(User, user_id)
    if user.role == ROLE_ADMIN:
        flash("The admin account can't be deleted.", "danger")
        return redirect(url_for("accounts.index"))
    db.session.delete(user)
    db.session.commit()
    flash(f"Account \"{user.username}\" deleted. Entries they created are kept.", "success")
    return redirect(url_for("accounts.index"))
