"""Sensor register and readings.

A sensor is registered with the plant stage it serves, its type, make and model, and optional low and high limits
from your own specification. Readings come in by hand or from the plant API; each reading is checked against the
sensor's limits at the time it is saved.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import audit, config
from .models import (
    SENSOR_OUTPUTS, SENSOR_STAGES, SENSOR_STATUSES, SENSOR_TYPES, Equipment, Sensor, SensorReading, User,
)
from .operations import _int_or_none, _parse_dt, _s
from .services import ValidationError, parse_num

RESULT_LABELS = {"ok": "Within limits", "low": "Below low limit", "high": "Above high limit", "nolimit": "No limit set"}
MAX_API_READINGS = 500


def check(value: float, low: float | None, high: float | None) -> str:
    if low is None and high is None:
        return "nolimit"
    if low is not None and value < low:
        return "low"
    if high is not None and value > high:
        return "high"
    return "ok"


def save_sensor(db: Session, user: User, form, s: Sensor | None = None) -> Sensor:
    errors: list[str] = []
    tag, name = _s(form, "tag"), _s(form, "name")
    if not tag:
        errors.append("Enter the sensor tag.")
    if not name:
        errors.append("Enter the sensor name.")
    dup = db.scalars(select(Sensor).where(func.lower(Sensor.tag) == tag.lower())).first() if tag else None
    if dup and (s is None or dup.id != s.id):
        errors.append("This sensor tag is already used.")
    stage, stype = _s(form, "stage"), _s(form, "sensor_type")
    if stage not in SENSOR_STAGES:
        errors.append("Select the plant stage.")
    if stype not in SENSOR_TYPES:
        errors.append("Select the sensor type.")
    output = _s(form, "output")
    if output and output not in SENSOR_OUTPUTS:
        errors.append("Select a valid output / interface.")
    status = _s(form, "status") or "In use"
    if status not in SENSOR_STATUSES:
        errors.append("Select a valid status.")
    low = parse_num(form.get("low_limit"), "Low limit", errors)
    high = parse_num(form.get("high_limit"), "High limit", errors)
    if low is not None and high is not None and low > high:
        errors.append("Low limit is greater than the high limit.")
    if (low is not None or high is not None) and not _s(form, "limit_source"):
        errors.append("Enter where the limits come from (standard, datasheet or in-house specification).")
    eq_id = _int_or_none(form.get("equipment_id"))
    if eq_id and not db.get(Equipment, eq_id):
        errors.append("Select equipment that exists.")
    if errors:
        raise ValidationError(errors)
    is_new = s is None
    before = None if is_new else {"low": s.low_limit, "high": s.high_limit, "status": s.status}
    if is_new:
        s = Sensor(tag=tag, name=name, stage=stage, sensor_type=stype)
        db.add(s)
    s.tag, s.name, s.stage, s.sensor_type = tag, name, stage, stype
    for k in ("parameter", "unit", "make", "model", "serial_no", "range_text", "accuracy_text", "location", "limit_source",
              "notes"):
        setattr(s, k, _s(form, k))
    s.output, s.status, s.low_limit, s.high_limit, s.equipment_id = output, status, low, high, eq_id
    db.flush()
    audit.record(db, user, "create" if is_new else "update", "sensor", s.tag,
                 {"before": before, "after": {"low": low, "high": high, "status": status}})
    db.commit()
    return s


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ref_exists(db: Session, ref: str) -> bool:
    from .models import Pack, ProcessBatch, SiteMix
    return bool(db.scalars(select(ProcessBatch.id).where(ProcessBatch.batch_no == ref)).first()
                or db.scalars(select(Pack.id).where(Pack.pack_no == ref)).first()
                or db.scalars(select(SiteMix.id).where(SiteMix.mix_no == ref)).first())


def add_reading(db: Session, user: User | None, s: Sensor, value, taken_at=None, note: str = "",
                source: str = "manual", commit: bool = True, ref: str = "") -> SensorReading:
    errors: list[str] = []
    ref = str(ref or "").strip().upper()
    if ref and not _ref_exists(db, ref):
        errors.append(f"No coating/grinding batch, bag or site mix with number {ref}.")
    v = parse_num(value, "Reading", errors)
    if v is None and not errors:
        errors.append("Enter the reading.")
    when = _parse_dt(taken_at, "Reading time", errors) if str(taken_at or "").strip() else _now_utc()
    if when and when > _now_utc() + timedelta(minutes=5):
        errors.append("Reading time is in the future.")
    if s.status == "Retired":
        errors.append(f"Sensor {s.tag} is retired.")
    if errors:
        raise ValidationError(errors)
    r = SensorReading(sensor_id=s.id, taken_at=when, value=v, result=check(v, s.low_limit, s.high_limit),
                      source=source, note=str(note or "").strip()[:300], entered_by_id=user.id if user else None,
                      ref=ref or None)
    db.add(r)
    if commit:
        db.flush()
        audit.record(db, user, "create", "sensor_reading", s.tag, {"value": v, "result": r.result, "source": source})
        db.commit()
    return r


def latest(db: Session) -> dict[int, SensorReading]:
    sub = select(SensorReading.sensor_id, func.max(SensorReading.taken_at).label("t")).group_by(SensorReading.sensor_id).subquery()
    rows = db.scalars(select(SensorReading).join(sub, (SensorReading.sensor_id == sub.c.sensor_id) &
                                                  (SensorReading.taken_at == sub.c.t))).all()
    return {r.sensor_id: r for r in rows}


def list_context(db: Session) -> dict:
    sensors = db.scalars(select(Sensor).options(selectinload(Sensor.equipment)).order_by(Sensor.stage, Sensor.tag)).all()
    last = latest(db)
    since = _now_utc() - timedelta(hours=24)
    out24 = dict(db.execute(select(SensorReading.sensor_id, func.count(SensorReading.id))
                            .where(SensorReading.taken_at >= since, SensorReading.result.in_(("low", "high")))
                            .group_by(SensorReading.sensor_id)).all())
    groups: dict[str, list] = {st: [] for st in SENSOR_STAGES}
    for s in sensors:
        groups.setdefault(s.stage, []).append(s)
    return {"groups": {k: v for k, v in groups.items() if v}, "last": last, "out24": out24, "count": len(sensors)}


def review_data(db: Session, date_from, date_to, limit: int) -> dict:
    """Out-of-limit sensor readings in the period, for the AI review."""
    start = datetime.combine(date_from, datetime.min.time(), config.TZ).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), config.TZ).astimezone(timezone.utc).replace(tzinfo=None)
    rows = db.execute(select(SensorReading, Sensor).join(Sensor, Sensor.id == SensorReading.sensor_id)
                      .where(SensorReading.taken_at >= start, SensorReading.taken_at < end,
                             SensorReading.result.in_(("low", "high")))
                      .order_by(SensorReading.taken_at.desc()).limit(limit)).all()
    return {"sensor_readings_outside_limits": [
        {"tag": s.tag, "sensor": s.name, "stage": s.stage, "parameter": s.parameter, "unit": s.unit,
         "time_utc": r.taken_at.isoformat(timespec="minutes"), "value": r.value, "low_limit": s.low_limit,
         "high_limit": s.high_limit, "limit_source": s.limit_source, "result": RESULT_LABELS[r.result]}
        for r, s in rows]}


# ---------------------------------------------------------------- readings that belong to a batch or site mix

STAGE_FOR = {"coating": "Coating (coarse aggregate)", "grinding": "Grinding (cementitious)",
             "sitemix": "Mixer on wheels and site mixing"}


def readings_for(db: Session, ref: str, kind: str, start: datetime | None, end: datetime | None) -> list[dict]:
    """Per-sensor summary of readings that belong to a record: readings sent with its number, plus readings
    without a number from sensors at the record's plant stage taken between its start and finish times."""
    cond = SensorReading.ref == ref
    if start and end:
        cond = cond | ((SensorReading.ref.is_(None)) & (Sensor.stage == STAGE_FOR.get(kind, "")) &
                       (SensorReading.taken_at >= start) & (SensorReading.taken_at <= end))
    rows = db.execute(select(SensorReading, Sensor).join(Sensor, Sensor.id == SensorReading.sensor_id).where(cond)
                      .order_by(Sensor.tag, SensorReading.taken_at)).all()
    out: dict[int, dict] = {}
    for r, s in rows:
        d = out.setdefault(s.id, {"sensor": s, "values": [], "outside": 0, "by_ref": 0, "by_time": 0})
        d["values"].append(r.value)
        d["outside"] += r.result in ("low", "high")
        d["by_ref" if r.ref == ref else "by_time"] += 1
    for d in out.values():
        v = d.pop("values")
        d.update(n=len(v), min=min(v), max=max(v), mean=sum(v) / len(v))
    return list(out.values())
