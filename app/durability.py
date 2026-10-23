"""Durability test results on strength samples (RCPT, chloride migration, water penetration and others).

Acceptance values are not built in: they are entered in Setup as targets with their source, either for all product
lines or for one product line. A result takes the target that applies when it is saved.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .models import DURABILITY_TESTS, CubeSample, DurabilityResult, DurabilityTarget, User
from .operations import _int_or_none, _s
from .services import ValidationError, parse_date, parse_num

RESULT_LABELS = {"pass": "Meets target", "fail": "Does not meet target", "notarget": "No target set"}


def product_line_of(sample: CubeSample) -> str:
    d = sample.dispatch
    if d and d.order and d.order.recipe:
        return d.order.recipe.product_line or ""
    return ""


def target_for(db: Session, test_type: str, product_line: str) -> DurabilityTarget | None:
    rows = db.scalars(select(DurabilityTarget).where(DurabilityTarget.test_type == test_type)).all()
    exact = [t for t in rows if product_line and t.product_line == product_line]
    general = [t for t in rows if not t.product_line]
    return (exact or general or [None])[0]


def judge(mean: float, lo: float | None, hi: float | None) -> str:
    if lo is None and hi is None:
        return "notarget"
    if (lo is not None and mean < lo) or (hi is not None and mean > hi):
        return "fail"
    return "pass"


def save_target(db: Session, user: User, form) -> DurabilityTarget:
    errors: list[str] = []
    ttype = _s(form, "test_type")
    if ttype not in DURABILITY_TESTS:
        errors.append("Select the test.")
    lo = parse_num(form.get("min_value"), "Minimum", errors)
    hi = parse_num(form.get("max_value"), "Maximum", errors)
    if lo is None and hi is None and not errors:
        errors.append("Enter a minimum, a maximum or both.")
    if lo is not None and hi is not None and lo > hi:
        errors.append("Minimum is greater than maximum.")
    source = _s(form, "source")
    if not source:
        errors.append("Enter the source of the target (specification, standard or in-house document).")
    line = _s(form, "product_line")
    if ttype in DURABILITY_TESTS and db.scalars(select(DurabilityTarget).where(
            DurabilityTarget.test_type == ttype, DurabilityTarget.product_line == line)).first():
        errors.append("A target for this test and product line already exists. Delete it first to change it.")
    if errors:
        raise ValidationError(errors)
    t = DurabilityTarget(test_type=ttype, product_line=line, min_value=lo, max_value=hi, source=source)
    db.add(t)
    db.flush()
    audit.record(db, user, "create", "durability_target", t.id,
                 {"test": ttype, "line": line or "all", "min": lo, "max": hi, "source": source})
    db.commit()
    return t


def add_result(db: Session, user: User, sample: CubeSample, form) -> DurabilityResult:
    errors: list[str] = []
    ttype = _s(form, "test_type")
    if ttype not in DURABILITY_TESTS:
        errors.append("Select the test.")
    tdate = parse_date(form.get("test_date"), "test date", errors)
    age_raw = _s(form, "age_days")
    age = _int_or_none(age_raw)
    if age_raw and (age is None or age < 0):
        errors.append("Age must be a whole number of days.")
    values = []
    for part in _s(form, "values").replace(";", ",").split(","):
        if part.strip():
            v = parse_num(part, "Specimen value", errors)
            if v is not None:
                values.append(v)
    if not values and not errors:
        errors.append("Enter at least one specimen value.")
    name, unit, method = DURABILITY_TESTS.get(ttype, ("", "", ""))
    if ttype == "other":
        name = _s(form, "other_name") or ""
        unit = _s(form, "other_unit")
        method = _s(form, "other_method") or "As entered"
        if not name:
            errors.append("Enter the name of the test.")
    if errors:
        raise ValidationError(errors)
    mean = sum(values) / len(values)
    t = target_for(db, ttype, product_line_of(sample)) if ttype != "other" else None
    lo, hi = (t.min_value, t.max_value) if t else (None, None)
    r = DurabilityResult(sample_id=sample.id, test_type=ttype, test_name=name, unit=unit, method=method, age_days=age,
                         test_date=tdate, values_text=", ".join(f"{v:g}" for v in values), mean_value=round(mean, 4),
                         target_min=lo, target_max=hi, target_source=t.source if t else "", result=judge(mean, lo, hi),
                         lab=_s(form, "lab"), remarks=_s(form, "remarks"), created_by_id=user.id)
    db.add(r)
    db.flush()
    audit.record(db, user, "create", "durability_result", sample.sample_no,
                 {"test": name, "mean": r.mean_value, "result": r.result})
    db.commit()
    return r


def results_for(db: Session, sample_id: int) -> list[DurabilityResult]:
    return db.scalars(select(DurabilityResult).where(DurabilityResult.sample_id == sample_id)
                      .order_by(DurabilityResult.test_date, DurabilityResult.id)).all()
