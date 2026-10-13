"""User accounts (administrators) and the audit trail."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, config
from ..db import get_db
from ..models import ROLES, AuditLog, User
from ..security import check_csrf, hash_password, require
from ..web import flash, redirect, render

router = APIRouter(dependencies=[Depends(check_csrf)])


def temp_password() -> str:
    """A readable one-time password: shown once, must be changed at first sign-in."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(12))
        if any(c.isdigit() for c in pw) and any(c.isupper() for c in pw) and any(c.islower() for c in pw):
            return pw


@router.get("/users")
def users_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require("users.manage"))):
    users = db.scalars(select(User).order_by(User.active.desc(), User.username)).all()
    return render(request, db, user, "users.html", users=users)


@router.get("/users/new")
def user_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("users.manage"))):
    return render(request, db, user, "user_form.html", u=None, form={})


@router.get("/users/{uid}")
def user_edit(uid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("users.manage"))):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Not found.")
    return render(request, db, user, "user_form.html", u=u, form={})


@router.post("/users/{uid}")
@router.post("/users/new")
async def user_save(request: Request, uid: int | None = None, db: Session = Depends(get_db),
                    user: User = Depends(require("users.manage"))):
    form = await request.form()
    u = db.get(User, uid) if uid else None
    if uid and not u:
        raise HTTPException(404, "Not found.")
    errors = []
    username = str(form.get("username", "")).strip().lower()
    role = str(form.get("role", ""))
    if u is None:
        if not username or not username.replace(".", "").replace("_", "").replace("-", "").isalnum():
            errors.append("Username may contain letters, digits, dots, dashes and underscores only.")
        elif db.scalars(select(User).where(func.lower(User.username) == username)).first():
            errors.append("This username is already taken.")
    if role not in ROLES:
        errors.append("Select a role.")
    active = form.get("active") == "on" if u else True
    if u and u.id == user.id and (role != "admin" or not active):
        errors.append("You cannot remove your own administrator role or deactivate yourself.")
    if errors:
        return render(request, db, user, "user_form.html", status_code=400, u=u, form=form, errors=errors)
    new_password = None
    if u is None:
        new_password = temp_password()
        u = User(username=username, role=role, password_hash=hash_password(new_password), must_change_password=True)
        db.add(u)
    before = {"role": u.role, "active": u.active, "full_name": u.full_name}
    u.full_name = str(form.get("full_name", "")).strip()
    u.role = role
    u.active = active
    if form.get("reset_password") == "on" and new_password is None:
        new_password = temp_password()
        u.password_hash = hash_password(new_password)
        u.must_change_password = True
    db.flush()
    audit.record(db, user, "create" if not uid else "update", "user", u.username,
                 {"before": before, "role": role, "active": active, "password_reset": bool(new_password and uid)})
    db.commit()
    if new_password:
        return render(request, db, user, "user_created.html", u=u, password=new_password)
    flash(request, f"User {u.username} saved.")
    return redirect("/users")


@router.get("/audit")
def audit_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require("audit.view"))):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except ValueError:
        page = 1
    q = request.query_params.get("q", "").strip().lower()
    stmt = select(AuditLog)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(func.lower(AuditLog.username).like(like) | func.lower(AuditLog.entity).like(like) |
                          func.lower(AuditLog.entity_id).like(like) | func.lower(AuditLog.action).like(like))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * config.PAGE_SIZE).limit(config.PAGE_SIZE)).all()
    return render(request, db, user, "audit.html", rows=rows, q=q, page=page,
                  pages=max(1, -(-total // config.PAGE_SIZE)))
