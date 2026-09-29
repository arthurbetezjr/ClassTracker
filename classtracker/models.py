import datetime as dt
from typing import Optional

from flask import current_app
from flask_login import UserMixin
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db

ROLE_ADMIN = "admin"
ROLE_USER = "user"

ENTRY_TYPES = {"meeting": "Cycle Meeting", "task": "Task", "exam": "Exam", "happened": "What Happened"}
# Each type is drawn as a gradient between two colors, both dark enough for white text (WCAG AA).
ENTRY_GRADIENTS = {
    "meeting": ("#2563eb", "#0e7490"),
    "task": ("#b45309", "#c2410c"),
    "exam": ("#e11d48", "#b91c1c"),
    "happened": ("#047857", "#0f766e"),
}
ENTRY_COLORS = {key: colors[0] for key, colors in ENTRY_GRADIENTS.items()}


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


enrollments = db.Table(
    "enrollments",
    db.Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("subject_code", ForeignKey("subjects.code", ondelete="CASCADE"), primary_key=True),
)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10), default=ROLE_USER)
    must_change_password: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Login throttling: too many wrong passwords in a row locks the account briefly.
    failed_logins: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))

    subjects: Mapped[list["Subject"]] = relationship(secondary=enrollments, back_populates="students")

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    def set_password(self, password):
        method = current_app.config.get("PASSWORD_HASH_METHOD", "scrypt")
        self.password_hash = generate_password_hash(password, method=method)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Subject(db.Model):
    __tablename__ = "subjects"

    # The subject code is the unique identifier and never changes after creation.
    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")

    students: Mapped[list[User]] = relationship(secondary=enrollments, back_populates="subjects")
    entries: Mapped[list["Entry"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan", passive_deletes=True
    )


class Entry(db.Model):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(10))  # a key of ENTRY_TYPES
    subject_code: Mapped[str] = mapped_column(ForeignKey("subjects.code", ondelete="CASCADE"))
    date: Mapped[dt.date]
    time: Mapped[Optional[dt.time]]
    end_time: Mapped[Optional[dt.time]]  # Cycle Meetings only
    meeting_link: Mapped[str] = mapped_column(String(500), default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    # Entries outlive the account that created them, so these become NULL on user delete.
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    # Soft delete: deleted entries stay visible to everyone, marked with the reason.
    deleted_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    deleted_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    delete_reason: Mapped[str] = mapped_column(Text, default="")

    subject: Mapped[Subject] = relationship(back_populates="entries")
    created_by: Mapped[Optional[User]] = relationship(foreign_keys=[created_by_id])
    deleted_by: Mapped[Optional[User]] = relationship(foreign_keys=[deleted_by_id])

    @property
    def public_id(self):
        return f"E-{self.id:05d}"


class EntryChange(db.Model):
    """Change log shown to the admin: every edit or delete of an entry, by anyone."""

    __tablename__ = "entry_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(10))  # "edit" or "delete"
    reason: Mapped[str] = mapped_column(Text)
    details: Mapped[str] = mapped_column(Text, default="", server_default="")  # what an edit changed
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    entry: Mapped[Entry] = relationship()
    actor: Mapped[Optional[User]] = relationship()
