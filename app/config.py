"""Application settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

APP_NAME = os.environ.get("APP_NAME", "Ayussha Plant QC")

# SQLite file in DATA_DIR by default. For PostgreSQL set e.g.
# DATABASE_URL=postgresql+psycopg://user:password@host:5432/plantqc
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'plantqc.db'}"


def _secret_key() -> str:
    """Use SECRET_KEY if given; otherwise create one once and keep it in DATA_DIR."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    path = DATA_DIR / "secret_key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_urlsafe(48)
    path.write_text(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


SECRET_KEY = _secret_key()

# Set to "true" when the app is served over HTTPS so the session cookie is marked Secure.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "12"))

# First administrator, created on first start only when no users exist.
INITIAL_ADMIN_USERNAME = os.environ.get("INITIAL_ADMIN_USERNAME", "admin")
INITIAL_ADMIN_PASSWORD = os.environ.get("INITIAL_ADMIN_PASSWORD", "")

# Claude API (optional). Without a key the AI review screen explains how to enable it.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
AI_MAX_RECORDS = int(os.environ.get("AI_MAX_RECORDS", "400"))

# Token for machine-to-machine posting of production records (plant system integration).
# Leave empty to keep the API switched off.
PLANT_API_TOKEN = os.environ.get("PLANT_API_TOKEN", "")

PAGE_SIZE = 50

# Time zone used to show timestamps and to decide "today".
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")
TZ = ZoneInfo(TIMEZONE)


def local_today():
    from datetime import datetime

    return datetime.now(TZ).date()

# Address printed in the QR code on bag labels, for example http://192.168.1.20:8000 so that a phone on the plant
# network can open the bag's page. If empty, the address used to open the app is used.
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
