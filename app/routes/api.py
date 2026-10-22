"""Machine-to-machine API for the plant control system.

Switched off unless PLANT_API_TOKEN is set. The plant system (or a small bridge program written once the
equipment supplier confirms its data interface) posts one production record per call.
"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import config, services
from ..db import get_db

router = APIRouter(prefix="/api/v1", tags=["plant API"])


def check_token(authorization: str = Header(default="")) -> None:
    if not config.PLANT_API_TOKEN:
        raise HTTPException(503, "The plant API is switched off. Set PLANT_API_TOKEN to enable it.")
    sent = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(sent, config.PLANT_API_TOKEN):
        raise HTTPException(401, "Invalid token.")


class ComponentIn(BaseModel):
    material: str = Field(description="Material name exactly as in Setup")
    lot_no: str = ""
    planned: float | None = None
    actual: float
    unit: str = "kg"


class ProductionIn(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    shift: str = ""
    record_no: str = ""
    product_line: str
    bags: int | None = None
    bag_target_kg: float | None = None
    total_actual_kg: float | None = None
    remarks: str = ""
    components: list[ComponentIn]


class SensorReadingIn(BaseModel):
    tag: str = Field(description="Sensor tag exactly as in the Sensors register")
    value: float
    taken_at: str = Field(default="", description="ISO date-time in plant time, e.g. 2026-10-22T14:05:00; empty = now")
    note: str = ""


class SensorReadingsIn(BaseModel):
    readings: list[SensorReadingIn]


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/production-records", dependencies=[Depends(check_token)])
def post_production(body: ProductionIn, db: Session = Depends(get_db)):
    form = {
        "prod_date": body.date, "shift": body.shift, "record_no": body.record_no, "product_line": body.product_line,
        "bags": body.bags, "bag_target_kg": body.bag_target_kg, "total_actual_kg": body.total_actual_kg,
        "remarks": body.remarks,
        "components": [{"material_name": c.material, "lot_no": c.lot_no, "planned": c.planned, "actual": c.actual,
                        "unit": c.unit} for c in body.components],
    }
    try:
        rec = services.save_production(db, None, form, source="api")
    except services.ValidationError as e:
        raise HTTPException(422, {"errors": e.messages})
    return {"id": rec.id, "record_no": rec.record_no, "status": rec.status, "max_abs_dev_pct": rec.max_abs_dev_pct,
            "lot_issue": rec.lot_issue}


@router.post("/sensor-readings", dependencies=[Depends(check_token)])
def post_sensor_readings(body: SensorReadingsIn, db: Session = Depends(get_db)):
    """Save readings from a PLC, gateway or data logger. All readings are saved, or none if any is rejected."""
    from sqlalchemy import func, select

    from .. import audit
    from .. import sensors as sn
    from ..models import Sensor
    if not body.readings:
        raise HTTPException(422, {"errors": ["Send at least one reading."]})
    if len(body.readings) > sn.MAX_API_READINGS:
        raise HTTPException(422, {"errors": [f"Send at most {sn.MAX_API_READINGS} readings per call."]})
    errors, saved = [], []
    for i, r in enumerate(body.readings, start=1):
        s = db.scalars(select(Sensor).where(func.lower(Sensor.tag) == r.tag.strip().lower())).first()
        if not s:
            errors.append(f"Reading {i}: no sensor with tag {r.tag}.")
            continue
        try:
            saved.append((s, sn.add_reading(db, None, s, r.value, r.taken_at, r.note, source="api", commit=False)))
        except services.ValidationError as e:
            errors += [f"Reading {i} ({r.tag}): {m}" for m in e.messages]
    if errors:
        db.rollback()
        raise HTTPException(422, {"errors": errors})
    db.flush()
    audit.record(db, None, "create", "sensor_reading", "api", {"count": len(saved)})
    db.commit()
    return {"saved": len(saved), "results": [{"tag": s.tag, "value": r.value, "result": r.result} for s, r in saved]}
