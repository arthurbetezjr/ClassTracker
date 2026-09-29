from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import select

from .extensions import db
from .models import User

MIN_PASSWORD_LENGTH = 8

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
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("home"))
        flash("Wrong username or password.", "danger")
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
