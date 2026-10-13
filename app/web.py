"""Shared helpers for the web pages: templates, flash messages, form parsing."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import config, logic
from .models import CATEGORIES, DECISIONS, ROLES, UNITS, User
from .security import can, csrf_token
from .services import get_settings

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def fmt_num(value, digits: int = 3) -> str:
    if value is None:
        return "—"
    text = f"{value:,.{digits}f}".rstrip("0").rstrip(".")
    return text if text not in ("-0", "") else "0"


def fmt_date(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d %b %Y")


def fmt_dt(value: datetime | None) -> str:
    """Timestamps are stored in UTC and shown in the plant's time zone (TIMEZONE setting)."""
    if not value:
        return "—"
    return value.replace(tzinfo=timezone.utc).astimezone(config.TZ).strftime("%d %b %Y %H:%M")


templates.env.filters["num"] = fmt_num
templates.env.filters["d"] = fmt_date
templates.env.filters["dt"] = fmt_dt
templates.env.globals.update(
    STATUS=logic.STATUS_LABELS, PROD=logic.PRODUCTION_LABELS, STRENGTH=logic.STRENGTH_LABELS, ROLES=ROLES, DECISIONS=DECISIONS,
    CATEGORIES=CATEGORIES, UNITS=UNITS, limit_text=logic.limit_text, limit_display=logic.limit_display, value_display=logic.value_display, APP_NAME=config.APP_NAME,
)


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", []).append([kind, message])


def render(request: Request, db: Session, user: User | None, name: str, status_code: int = 200, **ctx):
    messages = request.session.pop("flash", [])
    context = {
        "user": user,
        "can": lambda perm: can(user, perm),
        "csrf": csrf_token(request),
        "settings": get_settings(db),
        "messages": messages,
        "today": config.local_today().isoformat(),
        "path": request.url.path,
        **ctx,
    }
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def indexed_rows(form, prefix: str, fields: list[str]) -> list[dict]:
    """Collect rows posted as prefix-<n>-<field> into a list of dicts, in index order."""
    rows: dict[int, dict] = {}
    for key, value in form.multi_items():
        if not key.startswith(prefix + "-"):
            continue
        parts = key.split("-")
        if len(parts) != 3 or parts[2] not in fields:
            continue
        try:
            idx = int(parts[1])
        except ValueError:
            continue
        rows.setdefault(idx, {})[parts[2]] = value
    return [rows[i] for i in sorted(rows)]


def parse_period(date_from: str | None, date_to: str | None, default_days: int = 30) -> tuple[date, date]:
    try:
        end = date.fromisoformat(date_to) if date_to else config.local_today()
    except ValueError:
        end = config.local_today()
    try:
        start = date.fromisoformat(date_from) if date_from else end - timedelta(days=default_days - 1)
    except ValueError:
        start = end - timedelta(days=default_days - 1)
    if start > end:
        start, end = end, start
    return start, end
