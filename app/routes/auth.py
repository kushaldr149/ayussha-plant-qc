"""Sign in, sign out, change password, dashboard."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, config, services
from ..db import get_db
from ..models import User, utcnow
from ..security import (
    check_csrf, current_user, current_user_optional, hash_password, login_session, logout_session,
    password_problem, verify_password,
)
from ..web import flash, redirect, render

router = APIRouter(dependencies=[Depends(check_csrf)])

# Simple in-memory lockout against password guessing: 5 failures per username per 15 minutes.
_failures: dict[str, list] = {}


def _locked(username: str) -> bool:
    now = utcnow()
    recent = [t for t in _failures.get(username, []) if (now - t).total_seconds() < 900]
    _failures[username] = recent
    return len(recent) >= 5


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user_optional)):
    if user:
        return redirect("/")
    return render(request, db, None, "login.html", next=request.query_params.get("next", "/"))


@router.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = str(form.get("username", "")).strip().lower()
    password = str(form.get("password", ""))
    nxt = str(form.get("next") or "/")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    if _locked(username):
        return render(request, db, None, "login.html", status_code=429, next=nxt, username=username,
                      error="Too many failed attempts. Wait 15 minutes and try again.")
    user = db.scalars(select(User).where(func.lower(User.username) == username)).first()
    if not user or not user.active or not verify_password(password, user.password_hash):
        _failures.setdefault(username, []).append(utcnow())
        return render(request, db, None, "login.html", status_code=401, next=nxt, username=username,
                      error="Username or password is not correct.")
    _failures.pop(username, None)
    user.last_login = utcnow()
    audit.record(db, user, "login", "user", user.username)
    db.commit()
    login_session(request, user)
    return redirect("/account/password" if user.must_change_password else nxt)


@router.post("/logout")
def logout(request: Request):
    logout_session(request)
    return redirect("/login")


@router.get("/account/password")
def password_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return render(request, db, user, "password.html")


@router.post("/account/password")
async def password_change(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    current, new, confirm = (str(form.get(k, "")) for k in ("current", "new", "confirm"))
    error = None
    if not verify_password(current, user.password_hash):
        error = "Your current password is not correct."
    elif new != confirm:
        error = "The two new passwords do not match."
    elif new == current:
        error = "Choose a password different from the current one."
    else:
        error = password_problem(new)
    if error:
        return render(request, db, user, "password.html", status_code=400, error=error)
    user.password_hash = hash_password(new)
    user.must_change_password = False
    audit.record(db, user, "password_change", "user", user.username)
    db.commit()
    login_session(request, user)
    flash(request, "Password changed.")
    return redirect("/")


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    data = services.dashboard(db, config.local_today())
    settings = services.get_settings(db)
    steps = [
        ("Enter plant settings: plant name, product lines and batching tolerance",
         bool(settings.plant_name and settings.product_line_list and settings.tolerance_set)),
        ("Add the materials you receive", data["counts"]["materials"] > 0),
        ("Add test parameters with limits from your specifications", data["counts"]["parameters"] > 0),
        ("Add user accounts for QC, operators and management",
         (db.scalar(select(func.count(User.id))) or 0) > 1),
        ("Record the first inward material test", data["counts"]["tests"] > 0),
        ("Record the first production entry", data["counts"]["production"] > 0),
    ]
    from datetime import timedelta
    week_start = (config.local_today() - timedelta(days=6)).isoformat()
    today = config.local_today()
    from .. import operations as ops
    from ..models import NCR, Dispatch
    ncrs = db.scalars(select(NCR).where(NCR.status != "Closed").order_by(NCR.due_date.is_(None), NCR.due_date)).all()
    extra = {
        "ncr_open": len(ncrs),
        "ncr_overdue": [n for n in ncrs if n.due_date and n.due_date < today],
        "cal_due": ops.calibration_due(db, today),
        "strength_due": [x for x in ops.due_tests(db, today, ahead_days=0)],
        "low_stock": [m for m in ops.raw_stock(db) if m.low],
        "in_transit": db.scalar(select(func.count(Dispatch.id)).where(Dispatch.status == "Dispatched")) or 0,
    }
    return render(request, db, user, "dashboard.html", d=data, x=extra, steps=steps, week_start=week_start, now=today)
