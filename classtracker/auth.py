import datetime as dt
import math
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import select

from .extensions import db
from .models import User, utcnow
from .timeutil import as_utc

MIN_PASSWORD_LENGTH = 8
MAX_FAILED_LOGINS = 5
LOCKOUT = dt.timedelta(minutes=5)

bp = Blueprint("auth", __name__)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def normalize_username(username):
    # Usernames are stored lowercase so "Juan" and "juan" can't both exist.
    return username.strip().lower()


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    if request.method == "POST":
        username = normalize_username(request.form.get("username", ""))
        password = request.form.get("password", "")
        user = db.session.scalar(select(User).filter_by(username=username))
        if user is None:
            flash(f"There's no account with the username \"{username}\".", "danger")
        elif user.locked_until and as_utc(user.locked_until) > utcnow():
            minutes = math.ceil((as_utc(user.locked_until) - utcnow()).total_seconds() / 60)
            flash(f"Too many wrong passwords. Try again in {minutes} minute{'s' if minutes != 1 else ''}.", "danger")
        elif not user.check_password(password):
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.failed_logins = 0
                user.locked_until = utcnow() + LOCKOUT
                flash(f"Wrong password. Too many attempts, so this account is locked for "
                      f"{LOCKOUT.seconds // 60} minutes.", "danger")
            else:
                flash("Wrong password.", "danger")
            db.session.commit()
        else:
            user.failed_logins = 0
            user.locked_until = None
            db.session.commit()
            login_user(user)
            return redirect(url_for("home"))
    return render_template("login.html")


@bp.post("/logout")
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=["GET", "POST"])
def account():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not current_user.check_password(current):
            flash("Your current password is wrong.", "danger")
        elif len(new) < MIN_PASSWORD_LENGTH:
            flash(f"The new password must be at least {MIN_PASSWORD_LENGTH} characters.", "danger")
        elif new != confirm:
            flash("The new passwords don't match.", "danger")
        elif new == current:
            flash("The new password must be different from the current one.", "danger")
        else:
            current_user.set_password(new)
            current_user.must_change_password = False
            db.session.commit()
            flash("Password changed.", "success")
            return redirect(url_for("home"))
    return render_template("account.html", min_length=MIN_PASSWORD_LENGTH)
