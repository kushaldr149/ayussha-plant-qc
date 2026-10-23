"""Dispatch, strength tests, stock, NCRs and equipment: saving records and the calculations behind them."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from . import audit, config, logic
from .models import (
    CAL_RESULTS, DELIVERY_STATUSES, NCR, NCR_SOURCES, NCR_STATUSES, ORDER_STATUSES, VEHICLE_TYPES, Calibration,
    ConcreteGrade, CubeResult, CubeSample, Customer, Dispatch, DispatchItem, Equipment, Material, Order,
    ProductionComponent, ProductionRecord, QCTest, Site, StockAdjustment, User, Vehicle, utcnow,
)
from .services import ValidationError, parse_date, parse_num


def _s(form, key) -> str:
    return str(form.get(key) or "").strip()


def _int_or_none(value):
    try:
        return int(value) if str(value or "").strip() else None
    except ValueError:
        return None


def _next_no(db: Session, column, prefix: str, width: int) -> str:
    last = db.scalars(select(column).where(column.like(prefix + "%")).order_by(column.desc()).limit(1)).first()
    try:
        n = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    except (ValueError, IndexError):
        n = 1
    return f"{prefix}{n:0{width}d}"


def _parse_dt(value, label: str, errors: list[str]) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        local = datetime.fromisoformat(text)
    except ValueError:
        errors.append(f"{label} must be a date and time.")
        return None
    if local.tzinfo is None:
        local = local.replace(tzinfo=config.TZ)  # entered in plant time
    return local.astimezone(timezone.utc).replace(tzinfo=None)  # stored in UTC like every other timestamp


# ================================================================ masters

def save_customer(db: Session, user: User, form, customer: Customer | None = None) -> Customer:
    name = _s(form, "name")
    errors = []
    if not name:
        errors.append("Enter the customer name.")
    dup = db.scalars(select(Customer).where(func.lower(Customer.name) == name.lower())).first() if name else None
    if dup and (customer is None or dup.id != customer.id):
        errors.append("A customer with this name already exists.")
    if errors:
        raise ValidationError(errors)
    is_new = customer is None
    if is_new:
        customer = Customer(name=name)
        db.add(customer)
    customer.name = name
    for k in ("contact_person", "phone", "email", "address", "gstin"):
        setattr(customer, k, _s(form, k))
    customer.active = True if is_new else form.get("active") == "on"
    db.flush()
    audit.record(db, user, "create" if is_new else "update", "customer", customer.id, {"name": name})
    db.commit()
    return customer


def save_site(db: Session, user: User, form, site: Site | None = None) -> Site:
    errors = []
    customer = db.get(Customer, _int_or_none(form.get("customer_id")) or 0)
    name = _s(form, "name")
    if not customer:
        errors.append("Select the customer.")
    if not name:
        errors.append("Enter the site name.")
    if customer and name:
        dup = db.scalars(select(Site).where(Site.customer_id == customer.id, func.lower(Site.name) == name.lower())).first()
        if dup and (site is None or dup.id != site.id):
            errors.append("This customer already has a site with this name.")
    if errors:
        raise ValidationError(errors)
    is_new = site is None
    if is_new:
        site = Site(customer_id=customer.id, name=name)
        db.add(site)
    site.customer_id, site.name = customer.id, name
    for k in ("address", "contact_person", "phone"):
        setattr(site, k, _s(form, k))
    site.active = True if is_new else form.get("active") == "on"
    db.flush()
    audit.record(db, user, "create" if is_new else "update", "site", site.id, {"customer": customer.name, "name": name})
    db.commit()
    return site


def save_vehicle(db: Session, user: User, form, vehicle: Vehicle | None = None) -> Vehicle:
    reg = _s(form, "reg_no").upper()
    vtype = _s(form, "vehicle_type")
    errors = []
    if not reg:
        errors.append("Enter the registration or unit number.")
    if vtype not in VEHICLE_TYPES:
        errors.append("Select the vehicle type.")
    dup = db.scalars(select(Vehicle).where(func.upper(Vehicle.reg_no) == reg)).first() if reg else None
    if dup and (vehicle is None or dup.id != vehicle.id):
        errors.append("This vehicle is already registered.")
    if errors:
        raise ValidationError(errors)
    is_new = vehicle is None
    if is_new:
        vehicle = Vehicle(reg_no=reg, vehicle_type=vtype)
        db.add(vehicle)
    vehicle.reg_no, vehicle.vehicle_type = reg, vtype
    vehicle.description = _s(form, "description")
    vehicle.active = True if is_new else form.get("active") == "on"
    db.flush()
    audit.record(db, user, "create" if is_new else "update", "vehicle", vehicle.reg_no, {"type": vtype})
    db.commit()
    return vehicle


def save_grade(db: Session, user: User, form, grade: ConcreteGrade | None = None) -> ConcreteGrade:
    errors: list[str] = []
    name = _s(form, "name")
    if not name:
        errors.append("Enter the grade name.")
    dup = db.scalars(select(ConcreteGrade).where(func.lower(ConcreteGrade.name) == name.lower())).first() if name else None
    if dup and (grade is None or dup.id != grade.id):
        errors.append("This grade already exists.")
    spec = parse_num(form.get("specified_strength_mpa"), "Specified strength", errors)
    min_ind = parse_num(form.get("min_individual_mpa"), "Minimum individual result", errors)
    min_mean = parse_num(form.get("min_mean_mpa"), "Minimum mean result", errors)
    age_raw = _s(form, "acceptance_age_days")
    age = _int_or_none(age_raw)
    if age_raw and (age is None or age <= 0):
        errors.append("Acceptance age must be a whole number of days.")
    if (min_ind is not None or min_mean is not None) and age is None:
        errors.append("Enter the acceptance age the minimum values apply to.")
    if errors:
        raise ValidationError(errors)
    is_new = grade is None
    if is_new:
        grade = ConcreteGrade(name=name)
        db.add(grade)
    before = None if is_new else {"min_ind": grade.min_individual_mpa, "min_mean": grade.min_mean_mpa,
                                  "age": grade.acceptance_age_days}
    grade.name, grade.specified_strength_mpa, grade.acceptance_age_days = name, spec, age
    grade.min_individual_mpa, grade.min_mean_mpa = min_ind, min_mean
    grade.reference, grade.notes = _s(form, "reference"), _s(form, "notes")
    grade.active = True if is_new else form.get("active") == "on"
    db.flush()
    audit.record(db, user, "create" if is_new else "update", "grade", grade.name,
                 {"spec": spec, "age": age, "min_ind": min_ind, "min_mean": min_mean, "before": before})
    db.commit()
    return grade


# ================================================================ orders and dispatch

def save_order(db: Session, user: User, form, order: Order | None = None) -> Order:
    errors: list[str] = []
    order_date = parse_date(form.get("order_date"), "order date", errors)
    customer = db.get(Customer, _int_or_none(form.get("customer_id")) or 0)
    if not customer:
        errors.append("Select the customer.")
    site = db.get(Site, _int_or_none(form.get("site_id")) or 0) if form.get("site_id") else None
    if site and customer and site.customer_id != customer.id:
        errors.append("The site does not belong to this customer.")
    grade = db.get(ConcreteGrade, _int_or_none(form.get("grade_id")) or 0) if form.get("grade_id") else None
    from .models import Recipe
    recipe = db.get(Recipe, _int_or_none(form.get("recipe_id")) or 0) if form.get("recipe_id") else None
    qty = parse_num(form.get("quantity_m3"), "Quantity", errors)
    req = None
    if _s(form, "required_date"):
        req = parse_date(form.get("required_date"), "required date", errors)
    status = _s(form, "status") or "Open"
    if status not in ORDER_STATUSES:
        errors.append("Select a valid status.")
    order_no = _s(form, "order_no")
    if order_no:
        dup = db.scalars(select(Order).where(Order.order_no == order_no)).first()
        if dup and (order is None or dup.id != order.id):
            errors.append(f"Order number {order_no} already exists.")
    if errors:
        raise ValidationError(errors)
    is_new = order is None
    if is_new:
        order = Order(order_no=order_no or _next_no(db, Order.order_no, f"SO-{order_date.year}-", 4),
                      order_date=order_date, customer_id=customer.id, created_by_id=user.id)
        db.add(order)
    elif order_no:
        order.order_no = order_no
    order.order_date, order.customer_id = order_date, customer.id
    order.site_id = site.id if site else None
    order.grade_id = grade.id if grade else None
    order.recipe_id = recipe.id if recipe else None
    order.quantity_m3, order.required_date, order.status = qty, req, status
    order.customer_ref, order.remarks = _s(form, "customer_ref"), _s(form, "remarks")
    db.flush()
    audit.record(db, user, "create" if is_new else "update", "order", order.order_no,
                 {"customer": customer.name, "status": status})
    db.commit()
    return order


ACTIVE_DISPATCH = ("Dispatched", "Delivered")


def bags_dispatched(db: Session, production_ids: list[int], exclude_dispatch_id: int | None = None) -> dict[int, int]:
    if not production_ids:
        return {}
    stmt = (select(DispatchItem.production_id, func.coalesce(func.sum(DispatchItem.bags), 0))
            .join(Dispatch, Dispatch.id == DispatchItem.dispatch_id)
            .where(DispatchItem.production_id.in_(production_ids), Dispatch.status.in_(ACTIVE_DISPATCH)))
    if exclude_dispatch_id:
        stmt = stmt.where(Dispatch.id != exclude_dispatch_id)
    return {pid: int(n) for pid, n in db.execute(stmt.group_by(DispatchItem.production_id)).all()}


def finished_stock(db: Session) -> list[dict]:
    """Bags produced minus bags on active dispatches, per production record that still has bags."""
    records = db.scalars(select(ProductionRecord).where(ProductionRecord.bags.is_not(None), ProductionRecord.bags > 0)
                         .order_by(ProductionRecord.prod_date, ProductionRecord.id)).all()
    sent = bags_dispatched(db, [r.id for r in records])
    out = []
    for r in records:
        available = r.bags - sent.get(r.id, 0)
        if available > 0:
            out.append({"record": r, "produced": r.bags, "dispatched": sent.get(r.id, 0), "available": available,
                        "flagged": r.lot_issue or r.status == "over"})
    return out


def save_dispatch(db: Session, user: User, form) -> Dispatch:
    """form: dispatch_date, order_id, truck_id, mixer_id, driver_name, driver_phone, planned_m3, remarks,
    departed_at, items=[{production_id, bags}]"""
    errors: list[str] = []
    ddate = parse_date(form.get("dispatch_date"), "dispatch date", errors)
    order = db.get(Order, _int_or_none(form.get("order_id")) or 0)
    if not order:
        errors.append("Select the order.")
    elif order.status != "Open":
        errors.append(f"Order {order.order_no} is {order.status.lower()}; only open orders can be dispatched.")
    truck = db.get(Vehicle, _int_or_none(form.get("truck_id")) or 0) if form.get("truck_id") else None
    mixer = db.get(Vehicle, _int_or_none(form.get("mixer_id")) or 0) if form.get("mixer_id") else None
    planned = parse_num(form.get("planned_m3"), "Planned volume", errors)
    departed = _parse_dt(form.get("departed_at"), "Departure time", errors)
    remarks = _s(form, "remarks")

    rows = []
    for i, it in enumerate(form.get("items") or [], start=1):
        pid = _int_or_none(it.get("production_id"))
        if not pid and not str(it.get("bags") or "").strip():
            continue
        rec = db.get(ProductionRecord, pid or 0)
        if not rec:
            errors.append(f"Line {i}: select a production record.")
            continue
        bags = _int_or_none(it.get("bags"))
        if bags is None or bags <= 0:
            errors.append(f"Line {i}: enter the number of bags as a whole number.")
            continue
        rows.append((rec, bags))
    from .models import Pack
    packs = []
    for raw in form.get("pack_ids") or []:
        pk = db.get(Pack, _int_or_none(raw) or 0)
        if not pk:
            errors.append("A selected bag does not exist.")
        elif order and pk.order_id != order.id:
            errors.append(f"{pk.pack_no} was packed for another order.")
        elif pk.status != "Packed":
            errors.append(f"{pk.pack_no} is {pk.status.lower()}; only packed bags can be loaded.")
        else:
            packs.append(pk)
    if not rows and not packs and not errors:
        errors.append("Tick the bags and barrels loaded, or add a line with bags from a production record.")
    if rows:
        ids = [r.id for r, _ in rows]
        if len(set(ids)) != len(ids):
            errors.append("Each production record can appear only once per dispatch.")
        sent = bags_dispatched(db, ids)
        for rec, bags in rows:
            available = (rec.bags or 0) - sent.get(rec.id, 0)
            if bags > available:
                errors.append(f"{rec.record_no}: only {available} bag(s) available, {bags} entered.")
        flagged = [rec.record_no for rec, _ in rows if rec.lot_issue or rec.status == "over"]
        flagged += [pk.pack_no for pk in packs if pk.lot_issue or pk.batching_status == "over"]
        if flagged and not remarks and not errors:
            errors.append("Add a remark to dispatch bags from records flagged for lots not accepted or "
                          f"over tolerance ({', '.join(flagged)}).")
    if packs and not rows:
        flagged_packs = [pk.pack_no for pk in packs if pk.lot_issue or pk.batching_status == "over"]
        if flagged_packs and not remarks and not errors:
            errors.append("Add a remark to dispatch bags flagged for lots not accepted or over tolerance "
                          f"({', '.join(flagged_packs)}).")
    if errors:
        raise ValidationError(errors)

    disp = Dispatch(dispatch_no=_next_no(db, Dispatch.dispatch_no, f"DN-{ddate:%Y%m%d}-", 3), dispatch_date=ddate,
                    order_id=order.id, truck_id=truck.id if truck else None, mixer_id=mixer.id if mixer else None,
                    driver_name=_s(form, "driver_name"), driver_phone=_s(form, "driver_phone"), planned_m3=planned,
                    departed_at=departed or utcnow(), remarks=remarks, created_by_id=user.id,
                    items=[DispatchItem(production_id=rec.id, bags=bags) for rec, bags in rows])
    db.add(disp)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValidationError(["Another dispatch was saved at the same moment. Save again."])
    for pk in packs:
        pk.dispatch_id, pk.status = disp.id, "Loaded"
    audit.record(db, user, "create", "dispatch", disp.dispatch_no, {
        "order": order.order_no, "items": [(rec.record_no, bags) for rec, bags in rows],
        "packs": [pk.pack_no for pk in packs]})
    db.commit()
    return disp


def update_delivery(db: Session, user: User, disp: Dispatch, form) -> None:
    errors: list[str] = []
    status = _s(form, "status")
    if status not in DELIVERY_STATUSES:
        errors.append("Select the delivery status.")
    delivered_at = _parse_dt(form.get("delivered_at"), "Delivery time", errors)
    delivered_m3 = parse_num(form.get("delivered_m3"), "Volume placed", errors)
    if status == "Delivered" and not _s(form, "received_by"):
        errors.append("Enter who received the delivery at site.")
    if errors:
        raise ValidationError(errors)
    before = {"status": disp.status}
    disp.status = status
    disp.received_by = _s(form, "received_by")
    disp.delivered_m3 = delivered_m3
    disp.delivery_remarks = _s(form, "delivery_remarks")
    if status == "Delivered":
        disp.delivered_at = delivered_at or disp.delivered_at or utcnow()
        disp.delivered_by_id = user.id
    from .models import Pack
    for pk in db.scalars(select(Pack).where(Pack.dispatch_id == disp.id, Pack.status == "Loaded")).all():
        if status == "Cancelled":
            pk.dispatch_id, pk.status = None, "Packed"   # back in the plant, can be loaded again
        elif status == "Returned":
            pk.status = "Returned"
    audit.record(db, user, "update", "dispatch", disp.dispatch_no, {"before": before, "status": status})
    db.commit()


# ================================================================ strength tests

def save_sample(db: Session, user: User, form) -> CubeSample:
    errors: list[str] = []
    cast = parse_date(form.get("cast_date"), "casting date", errors)
    disp = db.get(Dispatch, _int_or_none(form.get("dispatch_id")) or 0) if form.get("dispatch_id") else None
    grade = db.get(ConcreteGrade, _int_or_none(form.get("grade_id")) or 0) if form.get("grade_id") else None
    if grade is None and disp and disp.order.grade_id:
        grade = disp.order.grade
    stype = _s(form, "specimen_type") or "Cube"
    if stype not in ("Cube", "Cylinder"):
        errors.append("Select cube or cylinder.")
    size = parse_num(form.get("specimen_size_mm"), "Specimen size", errors)
    if size is not None and size <= 0:
        errors.append("Specimen size must be more than zero.")
    ages_text = _s(form, "test_ages")
    probe = CubeSample(test_ages=ages_text)
    if ages_text and not probe.age_list:
        errors.append("Enter test ages as whole numbers of days separated by commas.")
    per_age = _int_or_none(form.get("specimens_per_age"))
    if errors:
        raise ValidationError(errors)
    sample = CubeSample(
        sample_no=_next_no(db, CubeSample.sample_no, f"CS-{cast.year}-", 5), dispatch_id=disp.id if disp else None,
        grade_id=grade.id if grade else None, cast_date=cast, cast_location=_s(form, "cast_location"),
        specimen_type=stype, specimen_size_mm=size, test_ages=",".join(str(a) for a in probe.age_list),
        specimens_per_age=per_age, fresh_notes=_s(form, "fresh_notes"), remarks=_s(form, "remarks"),
        created_by_id=user.id)
    db.add(sample)
    db.flush()
    audit.record(db, user, "create", "cube_sample", sample.sample_no,
                 {"dispatch": disp.dispatch_no if disp else None, "grade": grade.name if grade else None})
    db.commit()
    return sample


def add_results(db: Session, user: User, sample: CubeSample, form) -> list[CubeResult]:
    """form: age_days, test_date, rows=[{specimen_no, mass_kg, load_kn, strength_mpa}]"""
    errors: list[str] = []
    age = _int_or_none(form.get("age_days"))
    if age is None or age <= 0:
        errors.append("Enter the test age in days.")
    tdate = parse_date(form.get("test_date"), "test date", errors)
    if tdate and tdate < sample.cast_date:
        errors.append("The test date is before the casting date.")
    area = logic.loaded_area_mm2(sample.specimen_type, sample.specimen_size_mm)
    out = []
    for i, row in enumerate(form.get("rows") or [], start=1):
        if not any(str(row.get(k) or "").strip() for k in ("load_kn", "strength_mpa", "mass_kg")):
            continue
        load = parse_num(row.get("load_kn"), f"Specimen {i} load", errors)
        strength = parse_num(row.get("strength_mpa"), f"Specimen {i} strength", errors)
        mass = parse_num(row.get("mass_kg"), f"Specimen {i} mass", errors)
        if load is not None:
            if area is None:
                errors.append(f"Specimen {i}: the specimen size is not recorded, so strength cannot be calculated from load. "
                              "Enter the strength directly.")
                continue
            strength = logic.strength_from_load(load, area)
        if strength is None:
            errors.append(f"Specimen {i}: enter the failure load or the strength.")
            continue
        out.append(CubeResult(age_days=age or 0, test_date=tdate, specimen_no=str(row.get("specimen_no") or i).strip(),
                              mass_kg=mass, load_kn=load, strength_mpa=round(strength, 2), tested_by_id=user.id))
    if not out and not errors:
        errors.append("Enter at least one specimen result.")
    if errors:
        raise ValidationError(errors)
    sample.results.extend(out)
    audit.record(db, user, "create", "cube_results", sample.sample_no,
                 {"age": age, "strengths": [r.strength_mpa for r in out]})
    db.commit()
    return out


def sample_summary(sample: CubeSample) -> dict:
    """Per-age groups, the acceptance check and due dates."""
    grade = sample.grade
    by_age: dict[int, list[CubeResult]] = defaultdict(list)
    for r in sample.results:
        by_age[r.age_days].append(r)
    ages = sorted(set(sample.age_list) | set(by_age))
    groups = []
    for age in ages:
        values = [r.strength_mpa for r in by_age.get(age, [])]
        is_acc = bool(grade and grade.acceptance_age_days == age)
        g = logic.strength_group(values, grade.min_individual_mpa if is_acc else None,
                                 grade.min_mean_mpa if is_acc else None)
        g.update(age=age, due=sample.cast_date + timedelta(days=age), results=by_age.get(age, []), acceptance=is_acc)
        groups.append(g)
    acc = next((g for g in groups if g["acceptance"]), None)
    if acc is None:
        status = "noref"
    else:
        status = acc["status"]
    return {"groups": groups, "status": status}


def due_tests(db: Session, today: date, ahead_days: int = 7) -> list[dict]:
    samples = db.scalars(select(CubeSample).options(selectinload(CubeSample.results))
                         .where(CubeSample.cast_date >= today - timedelta(days=400))).all()
    out = []
    for s in samples:
        tested = {r.age_days for r in s.results}
        for age in s.age_list:
            due = s.cast_date + timedelta(days=age)
            if age not in tested and due <= today + timedelta(days=ahead_days):
                out.append({"sample": s, "age": age, "due": due, "overdue": due < today})
    out.sort(key=lambda x: x["due"])
    return out


# ================================================================ stock

@dataclass
class LotBalance:
    lot: str
    decision: str = ""
    received: float = 0.0
    used: float = 0.0
    adjusted: float = 0.0
    last_date: date | None = None

    @property
    def balance(self) -> float:
        return self.received - self.used + self.adjusted


@dataclass
class MaterialStock:
    material: Material
    unit: str
    lots: dict[str, LotBalance] = field(default_factory=dict)
    unconverted: list[str] = field(default_factory=list)

    @property
    def balance(self) -> float:
        return sum(l.balance for l in self.lots.values())

    @property
    def usable(self) -> float:
        return sum(l.balance for l in self.lots.values() if l.decision == "Accepted")

    @property
    def low(self) -> bool:
        return self.material.reorder_level is not None and self.usable < self.material.reorder_level


def raw_stock(db: Session) -> list[MaterialStock]:
    """Stock per material and lot = quantity received on QC tests (or produced by a coating/grinding batch)
    − used in production, coating, grinding and bags ± adjustments.

    Quantities are converted to the material's stock unit where the units are of the same kind (kg/t, L/mL).
    Quantities that cannot be converted are listed, not guessed.
    """
    materials = db.scalars(select(Material).order_by(Material.name)).all()
    stock = {m.id: MaterialStock(m, m.stock_unit or "kg") for m in materials}

    def lot_of(ms: MaterialStock, lot: str) -> LotBalance:
        key = (lot or "").strip()
        k = key.lower() or "(no lot)"
        if k not in ms.lots:
            ms.lots[k] = LotBalance(lot=key or "(no lot)")
        return ms.lots[k]

    from .models import Pack, PackItem, ProcessBatch, ProcessInput
    batches = db.scalars(select(ProcessBatch).order_by(ProcessBatch.batch_date, ProcessBatch.id)).all()
    batch_lots = {(b.output_material_id, b.output_lot_no.strip().lower()) for b in batches}
    for b in batches:  # output of coating / grinding is received into the in-house material's lot
        ms = stock.get(b.output_material_id)
        if ms is None:
            continue
        lb = lot_of(ms, b.output_lot_no)
        lb.decision = b.decision
        lb.last_date = b.batch_date
        q = logic.convert(b.output_qty, b.output_unit, ms.unit) if b.output_qty is not None else None
        if b.output_qty is not None and q is None:
            ms.unconverted.append(f"{b.batch_no}: {b.output_qty:g} {b.output_unit}")
        elif q is not None:
            lb.received += q
    usage = [(i.material_id, i.lot_no, i.qty, i.unit, d, n) for i, d, n in db.execute(
        select(ProcessInput, ProcessBatch.batch_date, ProcessBatch.batch_no)
        .join(ProcessBatch, ProcessBatch.id == ProcessInput.batch_id)).all()]
    usage += [(i.material_id, i.lot_no, i.actual, i.unit, d, n) for i, d, n in db.execute(
        select(PackItem, Pack.pack_date, Pack.pack_no).join(Pack, Pack.id == PackItem.pack_id)).all()]
    for mid, lot, qty, unit, d, ref in usage:
        ms = stock.get(mid)
        if ms is None:
            continue
        lb = lot_of(ms, lot)
        q = logic.convert(qty, unit, ms.unit)
        if q is None:
            ms.unconverted.append(f"{ref}: {qty:g} {unit}")
        else:
            lb.used += q
        lb.last_date = max(filter(None, [lb.last_date, d]))
    for t in db.scalars(select(QCTest).order_by(QCTest.test_date, QCTest.id)).all():
        ms = stock.get(t.material_id)
        if ms is None:
            continue
        if (t.material_id, (t.lot_no or "").strip().lower()) in batch_lots:
            continue  # a test on a coating/grinding output: the batch holds the quantity and the decision
        lb = lot_of(ms, t.lot_no)
        lb.decision = t.decision
        lb.last_date = t.test_date
        if t.quantity is None:
            continue
        q = logic.convert(t.quantity, t.unit, ms.unit)
        if q is None:
            ms.unconverted.append(f"{t.test_no}: {t.quantity:g} {t.unit}")
        else:
            lb.received += q
    comps = db.execute(select(ProductionComponent, ProductionRecord.prod_date, ProductionRecord.record_no)
                       .join(ProductionRecord, ProductionRecord.id == ProductionComponent.record_id)).all()
    for c, pdate, rno in comps:
        ms = stock.get(c.material_id)
        if ms is None:
            continue
        lb = lot_of(ms, c.lot_no)
        if not lb.decision and c.lot_no:
            lb.decision = "No QC record"
        q = logic.convert(c.actual, c.unit, ms.unit)
        if q is None:
            ms.unconverted.append(f"{rno}: {c.actual:g} {c.unit}")
        else:
            lb.used += q
        lb.last_date = max(filter(None, [lb.last_date, pdate]))
    for a in db.scalars(select(StockAdjustment)).all():
        ms = stock.get(a.material_id)
        if ms is None:
            continue
        lb = lot_of(ms, a.lot_no)
        q = logic.convert(a.quantity, a.unit, ms.unit)
        if q is None:
            ms.unconverted.append(f"adjustment {a.adj_date}: {a.quantity:g} {a.unit}")
        else:
            lb.adjusted += q
        lb.last_date = max(filter(None, [lb.last_date, a.adj_date]))
    return list(stock.values())


def save_adjustment(db: Session, user: User, form) -> StockAdjustment:
    errors: list[str] = []
    d = parse_date(form.get("adj_date"), "date", errors)
    material = db.get(Material, _int_or_none(form.get("material_id")) or 0)
    if not material:
        errors.append("Select the material.")
    qty = parse_num(form.get("quantity"), "Quantity", errors)
    if qty is None or qty == 0:
        errors.append("Enter the quantity to add (positive) or remove (negative).")
    unit = _s(form, "unit")
    if material and qty is not None and logic.convert(qty, unit, material.stock_unit or "kg") is None:
        errors.append(f"{unit} cannot be converted to this material's stock unit ({material.stock_unit or 'kg'}).")
    reason = _s(form, "reason")
    if not reason:
        errors.append("Enter the reason for the adjustment.")
    if errors:
        raise ValidationError(errors)
    adj = StockAdjustment(adj_date=d, material_id=material.id, lot_no=_s(form, "lot_no"), quantity=qty, unit=unit,
                          reason=reason, created_by_id=user.id)
    db.add(adj)
    db.flush()
    audit.record(db, user, "create", "stock_adjustment", adj.id,
                 {"material": material.name, "lot": adj.lot_no, "qty": qty, "unit": unit, "reason": reason})
    db.commit()
    return adj


# ================================================================ NCR

def save_ncr(db: Session, user: User, form, ncr: NCR | None = None, can_manage: bool = False) -> NCR:
    errors: list[str] = []
    is_new = ncr is None
    if is_new:
        raised = parse_date(form.get("raised_date"), "date raised", errors)
        source = _s(form, "source")
        if source not in NCR_SOURCES:
            errors.append("Select the source.")
        title, description = _s(form, "title"), _s(form, "description")
        if not title:
            errors.append("Enter a short title.")
        if not description:
            errors.append("Describe the non-conformance.")
    links = {}
    for key, model in (("qc_test_id", QCTest), ("production_id", ProductionRecord), ("dispatch_id", Dispatch),
                       ("cube_sample_id", CubeSample)):
        v = _int_or_none(form.get(key))
        if v and not db.get(model, v):
            errors.append("A linked record no longer exists.")
        links[key] = v
    due = parse_date(form.get("due_date"), "due date", errors) if _s(form, "due_date") else None
    owner_id = _int_or_none(form.get("owner_id"))
    if owner_id and not db.get(User, owner_id):
        errors.append("Select a valid owner.")
    status = _s(form, "status") or ("Open" if is_new else ncr.status)
    if status not in NCR_STATUSES:
        errors.append("Select a valid status.")
    if not is_new and not can_manage:
        errors.append("Only QC or administrators can update an NCR.")
    root, action, verification = _s(form, "root_cause"), _s(form, "corrective_action"), _s(form, "verification")
    if status == "Closed":
        if not root:
            errors.append("Enter the root cause before closing.")
        if not action:
            errors.append("Enter the corrective action before closing.")
        if not verification:
            errors.append("Enter how the action was verified before closing.")
    if errors:
        raise ValidationError(errors)
    if is_new:
        ncr = NCR(ncr_no=_next_no(db, NCR.ncr_no, f"NCR-{raised.year}-", 3), raised_date=raised, source=source,
                  title=title, description=description, raised_by_id=user.id, **links)
        db.add(ncr)
    before = None if is_new else {"status": ncr.status}
    ncr.containment = _s(form, "containment")
    if can_manage or is_new:
        ncr.owner_id = owner_id
        ncr.due_date = due
    if can_manage:
        ncr.root_cause, ncr.corrective_action, ncr.verification = root, action, verification
        if status == "Closed" and ncr.status != "Closed":
            ncr.closed_date, ncr.closed_by_id = config.local_today(), user.id
        if status != "Closed":
            ncr.closed_date, ncr.closed_by_id = None, None
        ncr.status = status
    db.flush()
    audit.record(db, user, "create" if is_new else "update", "ncr", ncr.ncr_no, {"before": before, "status": ncr.status})
    db.commit()
    return ncr


# ================================================================ equipment

EQUIPMENT_STATUSES = ["In use", "Out of service", "Retired"]


def save_equipment(db: Session, user: User, form, eq: Equipment | None = None) -> Equipment:
    errors: list[str] = []
    tag, name = _s(form, "tag"), _s(form, "name")
    if not tag:
        errors.append("Enter the equipment ID / tag.")
    if not name:
        errors.append("Enter the equipment name.")
    dup = db.scalars(select(Equipment).where(func.lower(Equipment.tag) == tag.lower())).first() if tag else None
    if dup and (eq is None or dup.id != eq.id):
        errors.append("This equipment ID is already used.")
    interval_raw = _s(form, "interval_days")
    interval = _int_or_none(interval_raw)
    if interval_raw and (interval is None or interval <= 0):
        errors.append("Calibration interval must be a whole number of days.")
    next_due = parse_date(form.get("next_due"), "next due date", errors) if _s(form, "next_due") else None
    status = _s(form, "status") or "In use"
    if status not in EQUIPMENT_STATUSES:
        errors.append("Select a valid status.")
    if errors:
        raise ValidationError(errors)
    is_new = eq is None
    if is_new:
        eq = Equipment(tag=tag, name=name)
        db.add(eq)
    eq.tag, eq.name = tag, name
    for k in ("location", "make_model", "serial_no", "range_text", "notes"):
        setattr(eq, k, _s(form, k))
    eq.interval_days, eq.status = interval, status
    if next_due or is_new:
        eq.next_due = next_due
    db.flush()
    audit.record(db, user, "create" if is_new else "update", "equipment", eq.tag, {"status": status, "next_due": eq.next_due})
    db.commit()
    return eq


def add_calibration(db: Session, user: User, eq: Equipment, form) -> Calibration:
    errors: list[str] = []
    cdate = parse_date(form.get("cal_date"), "calibration date", errors)
    result = _s(form, "result")
    if result not in CAL_RESULTS:
        errors.append("Select the calibration result.")
    next_due = parse_date(form.get("next_due"), "next due date", errors) if _s(form, "next_due") else None
    if next_due is None and cdate and eq.interval_days:
        next_due = cdate + timedelta(days=eq.interval_days)
    if next_due and cdate and next_due <= cdate:
        errors.append("The next due date must be after the calibration date.")
    if errors:
        raise ValidationError(errors)
    cal = Calibration(equipment_id=eq.id, cal_date=cdate, agency=_s(form, "agency"),
                      certificate_no=_s(form, "certificate_no"), result=result, next_due=next_due,
                      remarks=_s(form, "remarks"), created_by_id=user.id)
    db.add(cal)
    eq.next_due = next_due
    db.flush()
    audit.record(db, user, "create", "calibration", eq.tag, {"date": cdate, "result": result, "next_due": next_due})
    db.commit()
    return cal


def calibration_due(db: Session, today: date, ahead_days: int = 30) -> list[Equipment]:
    return db.scalars(select(Equipment).where(Equipment.status != "Retired", Equipment.next_due.is_not(None),
                                              Equipment.next_due <= today + timedelta(days=ahead_days))
                      .order_by(Equipment.next_due)).all()


# ================================================================ AI review data

def _dura(db: Session, sample_id: int) -> list:
    from .durability import results_for
    return results_for(db, sample_id)


def review_extra(db: Session, date_from: date, date_to: date, limit: int) -> dict:
    """Dispatch, strength and NCR records for the AI review (added to the QC and production data)."""
    dispatches = db.scalars(select(Dispatch).where(Dispatch.dispatch_date >= date_from, Dispatch.dispatch_date <= date_to)
                            .options(selectinload(Dispatch.items).selectinload(DispatchItem.production))
                            .order_by(Dispatch.dispatch_date.desc()).limit(limit)).all()
    samples = db.scalars(select(CubeSample).where(CubeSample.cast_date >= date_from, CubeSample.cast_date <= date_to)
                         .options(selectinload(CubeSample.results)).order_by(CubeSample.cast_date.desc()).limit(limit)).all()
    ncrs = db.scalars(select(NCR).where((NCR.raised_date >= date_from) | (NCR.status != "Closed"))
                      .order_by(NCR.raised_date.desc()).limit(limit)).all()
    out_samples = []
    for s in samples:
        sm = sample_summary(s)
        out_samples.append({
            "sample_no": s.sample_no, "cast_date": s.cast_date.isoformat(), "grade": s.grade.name if s.grade else None,
            "dispatch_no": s.dispatch.dispatch_no if s.dispatch else None,
            "customer": s.dispatch.order.customer.name if s.dispatch else None,
            "acceptance_values": ({"age_days": s.grade.acceptance_age_days, "min_individual_mpa": s.grade.min_individual_mpa,
                                   "min_mean_mpa": s.grade.min_mean_mpa} if s.grade else None),
            "ages": [{"age_days": g["age"], "results_mpa": [r.strength_mpa for r in g["results"]],
                      "mean_mpa": round(g["mean"], 2) if g["mean"] is not None else None, "check": g["status"]}
                     for g in sm["groups"]],
            "overall": sm["status"],
            "durability": [{"test": d.test_name, "method": d.method, "age_days": d.age_days, "mean": d.mean_value,
                            "unit": d.unit, "target_min": d.target_min, "target_max": d.target_max,
                            "target_source": d.target_source, "check": d.result}
                           for d in _dura(db, s.id)]})
    return {
        "dispatches": [{"dispatch_no": d.dispatch_no, "date": d.dispatch_date.isoformat(), "order_no": d.order.order_no,
                        "customer": d.order.customer.name, "status": d.status, "remarks": d.remarks,
                        "delivery_remarks": d.delivery_remarks,
                        "bags": [{"production_record": it.production.record_no, "bags": it.bags,
                                  "production_status": it.production.status, "lot_issue": it.production.lot_issue}
                                 for it in d.items]} for d in dispatches],
        "strength_samples": out_samples,
        "ncrs": [{"ncr_no": n.ncr_no, "raised": n.raised_date.isoformat(), "source": n.source, "title": n.title,
                  "status": n.status, "due": n.due_date.isoformat() if n.due_date else None,
                  "root_cause_recorded": bool(n.root_cause)} for n in ncrs],
    }
