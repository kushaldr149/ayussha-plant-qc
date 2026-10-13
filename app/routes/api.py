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
