"""Passwords, sessions, CSRF tokens and role checks."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models import User, utcnow

_ITERATIONS = 600_000

# What each role may do. Admin may do everything.
PERMISSIONS = {
    "view": {"admin", "qc", "operator", "management"},
    "qc.write": {"admin", "qc"},
    "qc.decide": {"admin", "qc"},
    "production.write": {"admin", "qc", "operator"},
    "reports": {"admin", "qc", "management"},
    "ai.review": {"admin", "qc", "management"},
    "setup.write": {"admin"},
    "users.manage": {"admin"},
    "records.delete": {"admin"},
    "audit.view": {"admin", "management"},
}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < 10:
        return "Use at least 10 characters."
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        return "Use upper and lower case letters and at least one digit."
    return None


def can(user: User | None, permission: str) -> bool:
    return bool(user and user.active and user.role in PERMISSIONS.get(permission, set()))


class LoginRequired(Exception):
    """Raised for pages that need a signed-in user; handled by redirecting to /login."""


class PasswordChangeRequired(Exception):
    """Raised when the user must set a new password before using the app."""


def login_session(request: Request, user: User) -> None:
    request.session.clear()
    request.session["uid"] = user.id
    request.session["exp"] = (utcnow() + timedelta(hours=config.SESSION_HOURS)).isoformat()
    request.session["csrf"] = secrets.token_urlsafe(32)


def logout_session(request: Request) -> None:
    request.session.clear()


def current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    exp = request.session.get("exp")
    if not uid or not exp:
        return None
    try:
        if datetime.fromisoformat(exp) < utcnow():
            request.session.clear()
            return None
    except ValueError:
        request.session.clear()
        return None
    user = db.get(User, uid)
    if not user or not user.active:
        request.session.clear()
        return None
    return user


def current_user(request: Request, user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise LoginRequired()
    if user.must_change_password and request.url.path not in ("/account/password", "/logout"):
        raise PasswordChangeRequired()
    return user


def require(permission: str):
    def checker(user: User = Depends(current_user)) -> User:
        if not can(user, permission):
            raise HTTPException(status_code=403, detail="Your role does not allow this.")
        return user

    return checker


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


async def check_csrf(request: Request) -> None:
    """Dependency for every form POST."""
    if request.method != "POST":
        return
    form = await request.form()
    sent = form.get("csrf_token", "")
    expected = request.session.get("csrf", "")
    if not expected or not hmac.compare_digest(str(sent), str(expected)):
        raise HTTPException(status_code=400, detail="The form expired. Go back, reload the page and submit again.")
