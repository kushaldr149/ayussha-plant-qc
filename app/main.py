"""Ayussha Plant: web application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import audit, config
from .db import SessionLocal, init_db
from .models import User
from .routes import api, auth, dispatch, masters, process, production, qc, quality, reports, setup, stock, strength, users
from .security import LoginRequired, PasswordChangeRequired, current_user_optional, hash_password, password_problem
from .services import get_settings
from .web import redirect, render

log = logging.getLogger("plantqc")


def bootstrap() -> None:
    """Create tables, the settings row and the first administrator."""
    init_db()
    with SessionLocal() as db:
        get_settings(db)
        from .services import apply_settings_file
        msg = apply_settings_file(db, config.DATA_DIR)
        if msg:
            log.warning(msg)
        if (db.scalar(select(func.count(User.id))) or 0) == 0:
            password = config.INITIAL_ADMIN_PASSWORD
            if not password:
                log.warning("No users exist and INITIAL_ADMIN_PASSWORD is not set; no administrator was created.")
                return
            problem = password_problem(password)
            if problem:
                raise SystemExit(f"INITIAL_ADMIN_PASSWORD is too weak: {problem}")
            admin = User(username=config.INITIAL_ADMIN_USERNAME.lower(), full_name="Administrator", role="admin",
                         password_hash=hash_password(password), must_change_password=True)
            db.add(admin)
            db.flush()
            audit.record(db, None, "create", "user", admin.username, {"role": "admin", "bootstrap": True})
            db.commit()
            log.warning("Created administrator '%s'. Sign in and change the password.", admin.username)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap()
    yield


app = FastAPI(title=config.APP_NAME, lifespan=lifespan, docs_url="/api/docs", redoc_url=None,
              openapi_url="/api/openapi.json")
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, session_cookie="plantqc_session",
                   max_age=config.SESSION_HOURS * 3600, same_site="lax", https_only=config.COOKIE_SECURE)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

for r in (auth.router, qc.router, production.router, setup.router, masters.router, dispatch.router, strength.router,
          stock.router, quality.router, users.router, reports.router, api.router, process.router):
    app.include_router(r)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if not request.url.path.startswith("/api/docs"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'")
    return response


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, _exc):
    nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return redirect(f"/login?next={nxt}")


@app.exception_handler(PasswordChangeRequired)
async def _pw_required(request: Request, _exc):
    return redirect("/account/password")


def _wants_json(request: Request) -> bool:
    return request.url.path.startswith("/api/")


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if _wants_json(request):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    with SessionLocal() as db:
        user = current_user_optional(request, db)
        titles = {403: "Not allowed", 404: "Not found", 400: "Request not accepted"}
        return render(request, db, user, "error.html", status_code=exc.status_code,
                      title=titles.get(exc.status_code, "Something went wrong"), detail=exc.detail)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    if _wants_json(request):
        return JSONResponse({"detail": exc.errors()}, status_code=422)
    with SessionLocal() as db:
        user = current_user_optional(request, db)
        return render(request, db, user, "error.html", status_code=400, title="Request not accepted",
                      detail="The address or form was not in the expected format.")
