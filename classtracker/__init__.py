import os

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from . import timeutil
from .extensions import csrf, db, login_manager
from .models import ENTRY_COLORS, ENTRY_GRADIENTS, ENTRY_TYPES, ROLE_ADMIN, User

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "12345"

# Pages reachable without logging in, and pages allowed while a password change is pending.
PUBLIC_ENDPOINTS = {"auth.login", "static"}
PASSWORD_CHANGE_ENDPOINTS = {"auth.account", "auth.logout"}

# create_all() never changes tables that already exist, so columns added after a table was first
# created in Neon are listed here as (table, column, DDL) and added on startup if missing.
ADDED_COLUMNS = [
    ("entry_changes", "details", "ALTER TABLE entry_changes ADD COLUMN details TEXT NOT NULL DEFAULT ''"),
    ("entries", "end_time", "ALTER TABLE entries ADD COLUMN end_time TIME"),
    ("users", "failed_logins", "ALTER TABLE users ADD COLUMN failed_logins INTEGER NOT NULL DEFAULT 0"),
    ("users", "locked_until", "ALTER TABLE users ADD COLUMN locked_until TIMESTAMP WITH TIME ZONE"),
    ("users", "entries_allowed", "ALTER TABLE users ADD COLUMN entries_allowed BOOLEAN NOT NULL DEFAULT FALSE"),
]


def create_app(test_config=None):
    load_dotenv()  # reads .env locally; on Vercel the variables are set in the dashboard
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=_database_url(),
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SESSION_COOKIE_SECURE="VERCEL" in os.environ,
        SESSION_COOKIE_SAMESITE="Lax",
        APP_TIMEZONE=os.environ.get("APP_TIMEZONE", "Asia/Manila"),
    )
    if test_config:
        app.config.update(test_config)
    for name in ("SECRET_KEY", "SQLALCHEMY_DATABASE_URI"):
        if not app.config[name]:
            raise RuntimeError(f"{name} is not configured (see .env / Vercel environment variables)")

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    from . import accounts, announcements, auth, entries, subjects

    app.register_blueprint(auth.bp)
    app.register_blueprint(accounts.bp)
    app.register_blueprint(subjects.bp)
    app.register_blueprint(entries.bp)
    app.register_blueprint(announcements.bp)

    app.jinja_env.filters["nice_date"] = timeutil.nice_date
    app.jinja_env.filters["nice_time"] = timeutil.nice_time
    app.jinja_env.filters["local_timestamp"] = timeutil.local_timestamp

    @app.context_processor
    def entry_type_info():
        return {"ENTRY_TYPES": ENTRY_TYPES, "ENTRY_COLORS": ENTRY_COLORS, "ENTRY_GRADIENTS": ENTRY_GRADIENTS}

    @app.context_processor
    def open_announcements():
        # base.html shows these as closable cards at the top of every page.
        shown = announcements.open_announcements() if current_user.is_authenticated else []
        return {"open_announcements": shown}

    @app.before_request
    def require_login():
        if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if current_user.must_change_password and request.endpoint not in PASSWORD_CHANGE_ENDPOINTS:
            flash("Please choose a new password before continuing.", "warning")
            return redirect(url_for("auth.account"))
        return None

    @app.get("/")
    def home():
        return render_template("calendar.html", subjects=entries.allowed_subjects())

    with app.app_context():
        db.create_all()
        _add_missing_columns()
        _ensure_default_admin()

    return app


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def _database_url():
    url = os.environ.get("DATABASE_URL")
    # Neon gives a plain postgresql:// URL; tell SQLAlchemy to use the psycopg (v3) driver.
    if url:
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _add_missing_columns():
    inspector = inspect(db.engine)
    columns = {}
    for table, column, ddl in ADDED_COLUMNS:
        if table not in columns:
            columns[table] = {c["name"] for c in inspector.get_columns(table)}
        if column not in columns[table]:
            with db.engine.begin() as connection:
                connection.execute(text(ddl))


def _ensure_default_admin():
    if db.session.scalar(select(User).filter_by(username=DEFAULT_ADMIN_USERNAME)):
        return
    admin = User(username=DEFAULT_ADMIN_USERNAME, role=ROLE_ADMIN, must_change_password=True)
    admin.set_password(DEFAULT_ADMIN_PASSWORD)
    db.session.add(admin)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()  # another server instance created it at the same moment
