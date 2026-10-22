"""Sensor register and readings pages."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import sensors as sn
from ..db import get_db
from ..models import SENSOR_OUTPUTS, SENSOR_STAGES, SENSOR_STATUSES, SENSOR_TYPES, Equipment, Sensor, SensorReading, User
from ..security import check_csrf, require
from ..services import ValidationError
from ..web import flash, redirect, render

router = APIRouter(dependencies=[Depends(check_csrf)])


def _opts(db: Session) -> dict:
    eq = db.scalars(select(Equipment).where(Equipment.status != "Retired").order_by(Equipment.tag)).all()
    return {"stages": SENSOR_STAGES, "types": SENSOR_TYPES, "outputs": SENSOR_OUTPUTS, "statuses": SENSOR_STATUSES,
            "equipment": eq}


def _get(db: Session, sid: int) -> Sensor:
    s = db.get(Sensor, sid)
    if not s:
        raise HTTPException(404, "This sensor does not exist.")
    return s


@router.get("/sensors")
def sensor_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return render(request, db, user, "sensor_list.html", labels=sn.RESULT_LABELS, types=SENSOR_TYPES,
                  stages=SENSOR_STAGES, **sn.list_context(db))


@router.get("/sensors/new")
def sensor_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("sensors.write"))):
    pre = {k: request.query_params.get(k) for k in ("stage", "sensor_type") if request.query_params.get(k)}
    return render(request, db, user, "sensor_form.html", s=None, form=pre, **_opts(db))


@router.post("/sensors/new")
async def sensor_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("sensors.write"))):
    form = await request.form()
    try:
        s = sn.save_sensor(db, user, form)
    except ValidationError as e:
        db.rollback()
        return render(request, db, user, "sensor_form.html", status_code=400, s=None, form=form, errors=e.messages,
                      **_opts(db))
    flash(request, f"Sensor {s.tag} added.")
    return redirect(f"/sensors/{s.id}")


@router.get("/sensors/{sid}")
def sensor_detail(sid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    s = _get(db, sid)
    readings = db.scalars(select(SensorReading).where(SensorReading.sensor_id == s.id)
                          .order_by(SensorReading.taken_at.desc()).limit(200)).all()
    return render(request, db, user, "sensor_detail.html", s=s, readings=readings, labels=sn.RESULT_LABELS, form={},
                  rform={}, **_opts(db))


@router.post("/sensors/{sid}")
async def sensor_update(sid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("sensors.write"))):
    s = _get(db, sid)
    form = await request.form()
    try:
        sn.save_sensor(db, user, form, s)
    except ValidationError as e:
        db.rollback()
        s = _get(db, sid)
        return render(request, db, user, "sensor_detail.html", status_code=400, s=s, readings=s.readings[:200],
                      labels=sn.RESULT_LABELS, form=form, rform={}, errors=e.messages, **_opts(db))
    flash(request, f"Sensor {s.tag} updated.")
    return redirect(f"/sensors/{s.id}")


@router.post("/sensors/{sid}/reading")
async def sensor_reading(sid: int, request: Request, db: Session = Depends(get_db),
                         user: User = Depends(require("sensors.reading"))):
    s = _get(db, sid)
    form = await request.form()
    try:
        r = sn.add_reading(db, user, s, form.get("value"), form.get("taken_at"), str(form.get("note", "")))
    except ValidationError as e:
        db.rollback()
        return render(request, db, user, "sensor_detail.html", status_code=400, s=s, readings=s.readings[:200],
                      labels=sn.RESULT_LABELS, form={}, rform=form, errors=e.messages, **_opts(db))
    flash(request, f"Reading saved: {sn.RESULT_LABELS[r.result].lower()}.", "warn" if r.result in ("low", "high") else "ok")
    return redirect(f"/sensors/{s.id}")
