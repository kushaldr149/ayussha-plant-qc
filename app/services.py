"""Saving and reading records. Used by the web forms, the CSV import and the plant API."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from . import audit, logic
from .models import (
    DECISIONS, Material, PlantSettings, ProductionComponent, ProductionRecord, QCParameter,
    QCResult, QCTest, Recipe, User, utcnow,
)


class ValidationError(Exception):
    def __init__(self, messages: list[str]):
        super().__init__("; ".join(messages))
        self.messages = messages


def get_settings(db: Session) -> PlantSettings:
    settings = db.get(PlantSettings, 1)
    if settings is None:
        settings = PlantSettings(id=1)
        db.add(settings)
        db.commit()
    return settings


def parse_date(value, label: str, errors: list[str]) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        errors.append(f"Enter the {label}.")
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        errors.append(f"The {label} must be a date in YYYY-MM-DD form.")
        return None


def parse_num(value, label: str, errors: list[str]) -> float | None:
    try:
        return logic.parse_number(value)
    except ValueError:
        errors.append(f"{label} must be a number.")
        return None


# ---------------------------------------------------------------- lots

@dataclass
class LotStatus:
    decision: str  # Accepted / On hold / Rejected / No QC record / ""
    test_id: int | None = None
    test_no: str = ""
    test_date: date | None = None


def lot_status(db: Session, material_id: int, lot_no: str) -> LotStatus:
    lot = (lot_no or "").strip()
    if not lot:
        return LotStatus("")
    test = db.scalars(
        select(QCTest)
        .where(QCTest.material_id == material_id, func.lower(QCTest.lot_no) == lot.lower())
        .order_by(QCTest.test_date.desc(), QCTest.id.desc())
        .limit(1)
    ).first()
    if not test:
        return LotStatus("No QC record")
    return LotStatus(test.decision, test.id, test.test_no, test.test_date)


def known_lots(db: Session) -> dict[int, list[dict]]:
    """Latest decision per (material, lot), for lot pick-lists in the production form."""
    rows = db.execute(
        select(QCTest.material_id, QCTest.lot_no, QCTest.decision, QCTest.test_date, QCTest.id)
        .where(QCTest.lot_no != "")
        .order_by(QCTest.test_date.desc(), QCTest.id.desc())
        .limit(3000)
    ).all()
    out: dict[int, list[dict]] = {}
    seen: set[tuple[int, str]] = set()
    for mid, lot, decision, tdate, _ in rows:
        key = (mid, lot.lower())
        if key in seen:
            continue
        seen.add(key)
        out.setdefault(mid, []).append({"lot": lot, "decision": decision, "date": tdate.isoformat()})
    return out


# ---------------------------------------------------------------- QC tests

def next_test_no(db: Session, test_date: date) -> str:
    prefix = f"QC-{test_date.year}-"
    last = db.scalars(
        select(QCTest.test_no).where(QCTest.test_no.like(prefix + "%")).order_by(QCTest.test_no.desc()).limit(1)
    ).first()
    n = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{n:05d}"


def save_qc_test(db: Session, user: User, form: dict) -> QCTest:
    """form keys: test_date, material_id, supplier, lot_no, vehicle_no, quantity, unit,
    decision, remarks, values = {parameter_id: raw value}."""
    errors: list[str] = []
    test_date = parse_date(form.get("test_date"), "test date", errors)
    material = None
    try:
        material = db.get(Material, int(form.get("material_id") or 0))
    except ValueError:
        pass
    if not material:
        errors.append("Select a material.")
    quantity = parse_num(form.get("quantity"), "Quantity received", errors)
    decision = (form.get("decision") or "").strip()
    if decision not in DECISIONS:
        errors.append("Select a decision for this lot.")
    remarks = (form.get("remarks") or "").strip()

    results: list[dict] = []
    if material:
        params = [p for p in material.parameters if p.active]
        if not params:
            errors.append("This material has no test parameters. Add them in Setup first.")
        values = form.get("values") or {}
        workings = form.get("workings") or {}
        for p in params:
            raw = values.get(str(p.id), values.get(p.id, ""))
            if p.value_type == "passfail":
                text = str(raw or "").strip().lower()
                if text not in ("", "pass", "fail", "1", "0"):
                    errors.append(f"{p.name}: choose Pass or Fail.")
                value = None if text == "" else (1.0 if text in ("pass", "1") else 0.0)
                lo, hi = 1.0, None
            else:
                value = parse_num(raw, p.name, errors)
                lo, hi = p.min_value, p.max_value
            work = workings.get(str(p.id), "")
            if work and len(work) > 20000:
                errors.append(f"{p.name}: worksheet data is too large.")
                work = ""
            results.append(dict(
                parameter_id=p.id, name=p.name, unit=p.unit, min_value=p.min_value, max_value=p.max_value,
                method=p.method, value=value, group_name=p.group_name or "", frequency=p.frequency or "Every lot",
                value_type=p.value_type or "number", workings=work or None,
                status=logic.evaluate(value, lo, hi, periodic=p.periodic),
            ))
        if params and not any(r["value"] is not None for r in results):
            errors.append("Enter at least one test value.")
    overall = logic.overall_status(r["status"] for r in results)
    if not errors and logic.accept_needs_remark(overall, decision, remarks):
        errors.append("Add a remark to accept a lot with out-of-limit results.")
    if errors:
        raise ValidationError(errors)

    for attempt in range(3):
        test = QCTest(
            test_no=next_test_no(db, test_date), test_date=test_date, material_id=material.id,
            material_name=material.name, category=material.category,
            supplier=(form.get("supplier") or "").strip(), lot_no=(form.get("lot_no") or "").strip(),
            vehicle_no=(form.get("vehicle_no") or "").strip(), quantity=quantity,
            unit=(form.get("unit") or "").strip(), overall=overall, decision=decision, remarks=remarks,
            created_by_id=user.id, decision_by_id=user.id, decision_at=utcnow(),
            results=[QCResult(**r) for r in results],
        )
        db.add(test)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            if attempt == 2:
                raise
            continue
        audit.record(db, user, "create", "qc_test", test.test_no, {
            "material": material.name, "lot": test.lot_no, "overall": overall, "decision": decision})
        db.commit()
        return test
    raise RuntimeError("unreachable")


def change_decision(db: Session, user: User, test: QCTest, decision: str, remarks: str) -> None:
    remarks = (remarks or "").strip()
    errors = []
    if decision not in DECISIONS:
        errors.append("Select a decision.")
    elif logic.accept_needs_remark(test.overall, decision, remarks):
        errors.append("Add a remark to accept a lot with out-of-limit results.")
    if errors:
        raise ValidationError(errors)
    before = {"decision": test.decision, "remarks": test.remarks}
    if decision != test.decision:
        test.decision = decision
        test.decision_by_id = user.id
        test.decision_at = utcnow()
    test.remarks = remarks
    audit.record(db, user, "update", "qc_test", test.test_no, {"before": before, "after": {"decision": decision, "remarks": remarks}})
    db.commit()


# ---------------------------------------------------------------- production

def next_record_no(db: Session, prod_date: date) -> str:
    prefix = f"PR-{prod_date:%Y%m%d}-"
    last = db.scalars(
        select(ProductionRecord.record_no).where(ProductionRecord.record_no.like(prefix + "%"))
        .order_by(ProductionRecord.record_no.desc()).limit(1)
    ).first()
    try:
        n = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    except ValueError:
        n = 1
    return f"{prefix}{n:03d}"


def save_production(db: Session, user: User | None, form: dict, source: str = "manual") -> ProductionRecord:
    """form keys: prod_date, shift, record_no, product_line, recipe_id, bags, bag_target_kg,
    total_actual_kg, remarks, components = [{material_id, lot_no, planned, actual, unit}]."""
    errors: list[str] = []
    prod_date = parse_date(form.get("prod_date"), "production date", errors)
    product_line = (form.get("product_line") or "").strip()
    if not product_line:
        errors.append("Select or enter the product line.")
    record_no = (form.get("record_no") or "").strip()
    if record_no and db.scalars(select(ProductionRecord.id).where(ProductionRecord.record_no == record_no)).first():
        errors.append(f"Record number {record_no} already exists.")
    recipe = None
    if form.get("recipe_id"):
        try:
            recipe = db.get(Recipe, int(form["recipe_id"]))
        except ValueError:
            recipe = None
    bags_f = parse_num(form.get("bags"), "Bags filled", errors)
    if bags_f is not None and (bags_f < 0 or bags_f != int(bags_f)):
        errors.append("Bags filled must be a whole number.")
    bag_target = parse_num(form.get("bag_target_kg"), "Target weight per bag", errors)
    total_actual = parse_num(form.get("total_actual_kg"), "Total actual weight", errors)

    settings = get_settings(db)
    components: list[ProductionComponent] = []
    for i, c in enumerate(form.get("components") or [], start=1):
        mid = c.get("material_id")
        if not mid and not any(str(c.get(k) or "").strip() for k in ("lot_no", "planned", "actual")):
            continue
        material = None
        try:
            material = db.get(Material, int(mid or 0))
        except ValueError:
            pass
        if material is None and c.get("material_name"):
            material = db.scalars(select(Material).where(func.lower(Material.name) == str(c["material_name"]).strip().lower())).first()
        if material is None:
            errors.append(f"Component {i}: select a material that exists in Setup.")
            continue
        planned = parse_num(c.get("planned"), f"Component {i} planned quantity", errors)
        actual = parse_num(c.get("actual"), f"Component {i} actual quantity", errors)
        if actual is None:
            errors.append(f"Component {i}: enter the actual quantity.")
            continue
        lot_no = str(c.get("lot_no") or "").strip()
        st = lot_status(db, material.id, lot_no)
        components.append(ProductionComponent(
            material_id=material.id, material_name=material.name, lot_no=lot_no, lot_decision=st.decision,
            lot_test_id=st.test_id, planned=planned, actual=actual, unit=(c.get("unit") or "kg").strip(),
            dev_pct=logic.deviation_pct(planned, actual), tolerance_pct=settings.tolerance_for(material.category),
        ))
    if not components and not errors:
        errors.append("Add at least one component with a material and actual quantity.")
    if errors:
        raise ValidationError(errors)

    status, largest = logic.item_status((c.dev_pct, c.tolerance_pct) for c in components)
    tolerance = logic.single_tolerance(c.tolerance_pct for c in components)
    record = ProductionRecord(
        record_no=record_no or next_record_no(db, prod_date), prod_date=prod_date,
        shift=(form.get("shift") or "").strip(), product_line=product_line,
        recipe_id=recipe.id if recipe else None, recipe_name=recipe.name if recipe else "",
        bags=int(bags_f) if bags_f is not None else None, bag_target_kg=bag_target, total_actual_kg=total_actual,
        tolerance_pct=tolerance, max_abs_dev_pct=largest, status=status,
        lot_issue=any(c.lot_no and c.lot_decision != "Accepted" for c in components),
        remarks=(form.get("remarks") or "").strip(), source=source,
        created_by_id=user.id if user else None, components=components,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValidationError([f"Record number {record.record_no} already exists."])
    audit.record(db, user, "create", "production", record.record_no, {
        "line": product_line, "status": status, "max_dev_pct": largest, "source": source})
    db.commit()
    return record


# ---------------------------------------------------------------- dashboard & review data

def dashboard(db: Session, today: date) -> dict:
    week = today - timedelta(days=6)
    qc7 = db.scalars(select(QCTest).where(QCTest.test_date >= week).options(selectinload(QCTest.results))).all()
    pr7 = db.scalars(select(ProductionRecord).where(ProductionRecord.prod_date >= week)).all()
    holds = db.scalars(select(QCTest).where(QCTest.decision == "On hold").order_by(QCTest.test_date.desc())).all()
    items = []
    for t in holds:
        items.append({"kind": "qc", "id": t.id, "date": t.test_date, "chip": ("hold", "On hold"),
                      "text": f"{t.material_name} · lot {t.lot_no or '—'}" + (f" · {t.supplier}" if t.supplier else "")})
    for t in qc7:
        if t.overall == "fail" and t.decision != "On hold":
            outs = ", ".join(r.name for r in t.results if r.status == "fail")
            items.append({"kind": "qc", "id": t.id, "date": t.test_date, "chip": ("fail", "Out of limit"),
                          "text": f"{t.material_name} · lot {t.lot_no or '—'} · {outs}"})
    for r in pr7:
        if r.status == "over":
            items.append({"kind": "prod", "id": r.id, "date": r.prod_date, "chip": ("fail", "Over tolerance"),
                          "text": f"{r.product_line} · {r.record_no} · max {r.max_abs_dev_pct:.2f}%"})
        if r.lot_issue:
            items.append({"kind": "prod", "id": r.id, "date": r.prod_date, "chip": ("hold", "Lot not accepted"),
                          "text": f"{r.product_line} · {r.record_no}"})
    items.sort(key=lambda i: i["date"], reverse=True)
    return {
        "qc7": len(qc7), "fail7": sum(1 for t in qc7 if t.overall == "fail"), "holds": len(holds),
        "prod7": len(pr7), "over7": sum(1 for r in pr7 if r.status == "over"), "items": items[:20],
        "counts": {
            "materials": db.scalar(select(func.count(Material.id))) or 0,
            "parameters": db.scalar(select(func.count(QCParameter.id))) or 0,
            "tests": db.scalar(select(func.count(QCTest.id))) or 0,
            "production": db.scalar(select(func.count(ProductionRecord.id))) or 0,
        },
    }


def review_data(db: Session, date_from: date, date_to: date, limit: int) -> dict:
    tests = db.scalars(
        select(QCTest).where(QCTest.test_date >= date_from, QCTest.test_date <= date_to)
        .options(selectinload(QCTest.results)).order_by(QCTest.test_date.desc()).limit(limit)
    ).all()
    records = db.scalars(
        select(ProductionRecord).where(ProductionRecord.prod_date >= date_from, ProductionRecord.prod_date <= date_to)
        .options(selectinload(ProductionRecord.components)).order_by(ProductionRecord.prod_date.desc()).limit(limit)
    ).all()
    settings = get_settings(db)
    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "batching_tolerance_pct_by_material_category": (settings.tolerance_map if settings.per_category
                                                         else {"all materials": settings.tolerance_pct}),
        "material_tests": [{
            "test_no": t.test_no, "date": t.test_date.isoformat(), "material": t.material_name, "category": t.category,
            "supplier": t.supplier, "lot": t.lot_no, "overall": t.overall, "decision": t.decision, "remarks": t.remarks,
            "results": [{"parameter": r.name, "unit": r.unit, "min": r.min_value, "max": r.max_value,
                         "value": r.value, "status": r.status} for r in t.results],
        } for t in tests],
        "production_records": [{
            "record_no": r.record_no, "date": r.prod_date.isoformat(), "shift": r.shift, "line": r.product_line,
            "status": r.status, "max_abs_deviation_pct": r.max_abs_dev_pct, "tolerance_pct": r.tolerance_pct,
            "remarks": r.remarks,
            "components": [{"material": c.material_name, "lot": c.lot_no, "lot_decision": c.lot_decision,
                            "planned": c.planned, "actual": c.actual, "unit": c.unit, "deviation_pct": c.dev_pct}
                           for c in r.components],
        } for r in records],
    }


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")
