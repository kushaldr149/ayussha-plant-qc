"""Plant process: coating and grinding batches, packing bags/barrels per order, and site mixing records.

Every input and every bag item is tied to a lot: either an inward lot (a Material QC test) or the output lot of a
coating/grinding batch. Lots that are not "Accepted", and bags outside the batching tolerance, are flagged and
need a written remark, the same rule as in the production log.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from . import audit, logic
from .models import (
    DECISIONS, PACK_KINDS, PROCESS_INPUTS, PROCESS_KINDS, PROCESS_OUTPUT, CubeSample, Dispatch, Equipment, Material,
    Order, Pack, PackItem, ProcessBatch, ProcessInput, QCTest, Recipe, SiteMix, SiteMixAdmixture, User, utcnow,
)
from .operations import _int_or_none, _next_no, _parse_dt, _s
from .services import ValidationError, get_settings, parse_date, parse_num

ROLE_LABELS = {"aggregate": "Aggregate", "coating": "Coating material", "feed": "Material ground"}
KG_UNITS = ("kg", "t")


# ---------------------------------------------------------------- lots

@dataclass
class Lot:
    key: str                # "qc:<test id>" or "pb:<batch id>"
    material: Material
    lot_no: str
    decision: str
    balance: float | None   # in the material's stock unit, None when not known
    unit: str
    test_id: int | None = None
    batch_id: int | None = None

    @property
    def label(self) -> str:
        bal = f" · balance {self.balance:,.0f} {self.unit}" if self.balance is not None else ""
        return f"{self.material.name} · lot {self.lot_no or '(no lot)'} · {self.decision or 'No decision'}{bal}"


def available_lots(db: Session, categories: tuple[str, ...]) -> list[Lot]:
    """Lots of materials in the given categories: the latest QC test per (material, lot) and every process batch output."""
    from .operations import raw_stock
    stock = {ms.material.id: ms for ms in raw_stock(db)}
    mats = {m.id: m for m in db.scalars(select(Material).where(Material.category.in_(categories),
                                                                Material.active.is_(True))).all()}
    if not mats:
        return []
    batch_lots = {(b.output_material_id, b.output_lot_no.strip().lower()): b
                  for b in db.scalars(select(ProcessBatch).where(ProcessBatch.output_material_id.in_(mats))).all()}
    latest: dict[tuple[int, str], QCTest] = {}
    for t in db.scalars(select(QCTest).where(QCTest.material_id.in_(mats)).order_by(QCTest.test_date, QCTest.id)).all():
        k = (t.material_id, (t.lot_no or "").strip().lower())
        if k not in batch_lots:
            latest[k] = t

    def bal(mid: int, lot: str):
        ms = stock.get(mid)
        lb = ms.lots.get((lot or "").strip().lower() or "(no lot)") if ms else None
        return (round(lb.balance, 3) if lb else None), (ms.unit if ms else "kg")

    out = []
    for (mid, _), t in latest.items():
        b, u = bal(mid, t.lot_no)
        out.append(Lot(f"qc:{t.id}", mats[mid], t.lot_no, t.decision, b, u, test_id=t.id))
    for (mid, _), pb in batch_lots.items():
        b, u = bal(mid, pb.output_lot_no)
        out.append(Lot(f"pb:{pb.id}", mats[mid], pb.output_lot_no, pb.decision, b, u, batch_id=pb.id))
    out.sort(key=lambda lt: (lt.material.name.lower(), lt.lot_no.lower()))
    return out


def _resolve_lot(db: Session, key: str, categories: tuple[str, ...]) -> tuple[Material, str, str, int | None, int | None]:
    """Return (material, lot_no, decision, test_id, batch_id) for a lot key, or raise ValueError."""
    kind, _, raw = (key or "").partition(":")
    ident = _int_or_none(raw)
    if kind == "qc" and ident:
        t = db.get(QCTest, ident)
        mat = db.get(Material, t.material_id) if t else None
        if mat and mat.category in categories:
            return mat, t.lot_no, t.decision, t.id, None
    if kind == "pb" and ident:
        b = db.get(ProcessBatch, ident)
        if b and b.output_material.category in categories:
            return b.output_material, b.output_lot_no, b.decision, None, b.id
    raise ValueError("select a lot from the list")


# ---------------------------------------------------------------- coating and grinding

def process_options(db: Session, kind: str) -> dict:
    roles = PROCESS_INPUTS[kind]
    return {
        "kind": kind, "label": PROCESS_KINDS[kind], "roles": {r: ROLE_LABELS[r] for r in roles},
        "lots": {r: available_lots(db, cats) for r, cats in roles.items()},
        "outputs": db.scalars(select(Material).where(Material.category == PROCESS_OUTPUT[kind], Material.active.is_(True))
                              .order_by(Material.name)).all(),
        "output_category": PROCESS_OUTPUT[kind],
        "equipment": db.scalars(select(Equipment).order_by(Equipment.tag)).all(),
    }


def save_process_batch(db: Session, user: User, kind: str, form) -> ProcessBatch:
    """form: batch_date, shift, equipment_id, output_material_id, output_qty, output_unit, blaine, residue45, remarks,
    inputs=[{role, lot, qty, unit}]"""
    if kind not in PROCESS_KINDS:
        raise ValidationError(["Unknown process."])
    errors: list[str] = []
    bdate = parse_date(form.get("batch_date"), "batch date", errors)
    out_mat = db.get(Material, _int_or_none(form.get("output_material_id")) or 0)
    if not out_mat or out_mat.category != PROCESS_OUTPUT[kind]:
        errors.append(f"Select the output material (category {PROCESS_OUTPUT[kind]}). Add it in Setup if it is not listed.")
    out_qty = parse_num(form.get("output_qty"), "Output quantity", errors)
    out_unit = _s(form, "output_unit") or "kg"
    if out_unit not in KG_UNITS:
        errors.append("Output unit must be kg or t.")
    if out_qty is not None and out_qty <= 0:
        errors.append("Output quantity must be more than zero.")
    eq = db.get(Equipment, _int_or_none(form.get("equipment_id")) or 0) if form.get("equipment_id") else None
    blaine = parse_num(form.get("blaine"), "Blaine fineness", errors) if kind == "grinding" else None
    residue = parse_num(form.get("residue45"), "Residue on 45 µm", errors) if kind == "grinding" else None
    remarks = _s(form, "remarks")
    started = _parse_dt(form.get("started_at"), "Start time", errors)
    finished = _parse_dt(form.get("finished_at"), "Finish time", errors)
    if started and finished and finished < started:
        errors.append("Finish time is before the start time.")

    rows = []
    for i, it in enumerate(form.get("inputs") or [], start=1):
        role, key = str(it.get("role", "")), str(it.get("lot", ""))
        if not key and not str(it.get("qty") or "").strip():
            continue
        if role not in PROCESS_INPUTS[kind]:
            errors.append(f"Input line {i}: unknown input type.")
            continue
        try:
            mat, lot_no, decision, test_id, batch_id = _resolve_lot(db, key, PROCESS_INPUTS[kind][role])
        except ValueError as e:
            errors.append(f"Input line {i}: {e}.")
            continue
        qty = parse_num(it.get("qty"), f"Input line {i} quantity", errors)
        unit = str(it.get("unit") or "kg")
        if qty is None or qty <= 0:
            errors.append(f"Input line {i}: enter the quantity used.")
            continue
        if unit not in KG_UNITS:
            errors.append(f"Input line {i}: unit must be kg or t.")
            continue
        rows.append((role, mat, lot_no, decision, test_id, qty, unit))
    for role in PROCESS_INPUTS[kind]:
        if not any(r[0] == role for r in rows):
            errors.append(f"Add at least one {ROLE_LABELS[role].lower()} lot.")
    if kind == "grinding" and len({r[1].id for r in rows}) > 1:
        errors.append("A grinding batch grinds one material: all input lots must be of the same material.")
    lot_issue = any(r[3] != "Accepted" for r in rows)
    if lot_issue and not remarks and not errors:
        bad = ", ".join(f"{r[1].name} lot {r[2] or '(no lot)'} ({r[3] or 'no decision'})" for r in rows if r[3] != "Accepted")
        errors.append(f"Add a remark to use lots that are not accepted: {bad}.")
    if errors:
        raise ValidationError(errors)

    coating_pct = target = dev = tol = cstatus = None
    if kind == "coating":
        agg = sum(logic.convert(r[5], r[6], "kg") for r in rows if r[0] == "aggregate")
        coat = sum(logic.convert(r[5], r[6], "kg") for r in rows if r[0] == "coating")
        coating_pct = round(coat / agg * 100, 3) if agg else None
        target = out_mat.coating_target_pct
        if target is None:
            cstatus = "notarget"
        elif agg:
            settings = get_settings(db)
            tols = [t for t in (settings.tolerance_for(r[1].category) for r in rows if r[0] == "coating") if t is not None]
            tol = min(tols) if tols else None
            dev = logic.deviation_pct(target / 100 * agg, coat)
            cstatus, _ = logic.item_status([(dev, tol)])
            if cstatus == "over" and not remarks:
                raise ValidationError([
                    f"Coating dosage is {coating_pct:.3f} % of the aggregate mass; the target for {out_mat.name} is "
                    f"{target:g} % (coating mass {dev:+.2f} % from target, tolerance ± {tol:g} %). Add a remark to save it."])
    prefix = {"coating": "CB", "grinding": "GB"}[kind]
    b = ProcessBatch(batch_no=_next_no(db, ProcessBatch.batch_no, f"{prefix}-{bdate:%Y%m%d}-", 3), kind=kind,
                     batch_date=bdate, shift=_s(form, "shift"), equipment_id=eq.id if eq else None,
                     output_material_id=out_mat.id, output_material_name=out_mat.name, output_qty=out_qty,
                     output_unit=out_unit, coating_pct=coating_pct, blaine_m2kg=blaine, residue45_pct=residue,
                     coating_target_pct=target, coating_dev_pct=dev, coating_tol_pct=tol, coating_status=cstatus,
                     started_at=started, finished_at=finished,
                     lot_issue=lot_issue, decision="On hold", remarks=remarks, created_by_id=user.id,
                     inputs=[ProcessInput(role=r[0], material_id=r[1].id, material_name=r[1].name, lot_no=r[2],
                                          lot_decision=r[3], lot_test_id=r[4], qty=r[5], unit=r[6]) for r in rows])
    b.output_lot_no = "pending"
    db.add(b)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValidationError(["Another batch was saved at the same moment. Save again."])
    b.output_lot_no = b.batch_no
    audit.record(db, user, "create", "process_batch", b.batch_no, {
        "kind": kind, "output": out_mat.name, "inputs": [(r[1].name, r[2], r[5], r[6]) for r in rows]})
    db.commit()
    return b


def set_batch_decision(db: Session, user: User, b: ProcessBatch, form) -> None:
    decision = _s(form, "decision")
    remarks = _s(form, "remarks")
    errors = []
    if decision not in DECISIONS:
        errors.append("Select a decision.")
    qc_id = _int_or_none(form.get("qc_test_id"))
    test = None
    if qc_id:
        test = db.get(QCTest, qc_id)
        if not test or test.material_id != b.output_material_id:
            errors.append("The linked QC test must be a test of the batch's output material.")
    if decision == "Accepted" and b.lot_issue and not remarks:
        errors.append("This batch used lots that were not accepted. Add a remark to accept its output.")
    if decision == "Accepted" and test and test.overall == "fail" and not remarks:
        errors.append("The linked QC test has out-of-limit results. Add a remark to accept the output.")
    if errors:
        raise ValidationError(errors)
    before = b.decision
    b.decision, b.decision_by_id, b.decision_at = decision, user.id, utcnow()
    b.qc_test_id = test.id if test else None
    if remarks:
        b.remarks = remarks
    audit.record(db, user, "decision", "process_batch", b.batch_no, {"before": before, "after": decision,
                                                                     "qc_test": test.test_no if test else None})
    db.commit()


# ---------------------------------------------------------------- packing

def planned_for(order: Order | None, kind: str) -> dict[int, tuple[float, str]]:
    """Planned quantity per material for one bag of this kind, from the order's mix design."""
    if not order or not order.recipe:
        return {}
    cats = PACK_KINDS[kind]
    return {c.material_id: (c.quantity, c.unit) for c in order.recipe.components if c.material.category in cats}


def pack_options(db: Session, order: Order | None, kind: str | None) -> dict:
    orders = db.scalars(select(Order).where(Order.status == "Open").options(selectinload(Order.customer))
                        .order_by(Order.order_date.desc(), Order.id.desc())).all()
    ctx = {"orders": orders, "kinds": list(PACK_KINDS), "order": order, "kind": kind, "lots": [], "planned": {}}
    if kind in PACK_KINDS:
        ctx["lots"] = available_lots(db, PACK_KINDS[kind])
        planned = planned_for(order, kind)
        mats = {m.id: m for m in db.scalars(select(Material).where(Material.id.in_(planned))).all()} if planned else {}
        ctx["planned"] = [(mats[mid], q, u) for mid, (q, u) in planned.items() if mid in mats]
    return ctx


def save_packs(db: Session, user: User, form) -> list[Pack]:
    """form: order_id, kind, pack_date, copies, gross_kg, remarks, items=[{lot, actual, unit}].
    Creates `copies` packs with the same contents (each has its own number and label)."""
    errors: list[str] = []
    order = db.get(Order, _int_or_none(form.get("order_id")) or 0)
    if not order:
        errors.append("Select the order the bag is packed for.")
    elif order.status != "Open":
        errors.append(f"Order {order.order_no} is {order.status.lower()}.")
    kind = _s(form, "kind")
    if kind not in PACK_KINDS:
        errors.append("Select what is being packed.")
        raise ValidationError(errors)
    pdate = parse_date(form.get("pack_date"), "packing date", errors)
    copies = _int_or_none(form.get("copies")) or 1
    if not 1 <= copies <= 50:
        errors.append("Number of identical bags must be between 1 and 50.")
    gross = parse_num(form.get("gross_kg"), "Gross mass", errors)
    remarks = _s(form, "remarks")

    rows = []
    for i, it in enumerate(form.get("items") or [], start=1):
        key = str(it.get("lot", ""))
        if not key and not str(it.get("actual") or "").strip():
            continue
        try:
            mat, lot_no, decision, test_id, batch_id = _resolve_lot(db, key, PACK_KINDS[kind])
        except ValueError as e:
            errors.append(f"Line {i}: {e}.")
            continue
        actual = parse_num(it.get("actual"), f"Line {i} quantity", errors)
        unit = str(it.get("unit") or "kg")
        if actual is None or actual <= 0:
            errors.append(f"Line {i}: enter the quantity packed.")
            continue
        if logic.unit_kind(unit) is None:
            errors.append(f"Line {i}: select a unit.")
            continue
        rows.append([mat, lot_no, decision, test_id, batch_id, actual, unit])
    if not rows and not errors:
        errors.append("Add at least one line with a lot and the quantity packed.")
    if errors:
        raise ValidationError(errors)

    planned = planned_for(order, kind)
    settings = get_settings(db)
    tol_of = {mid: settings.tolerance_for(m.category) for mid in planned if (m := db.get(Material, mid))}
    for mat, *_ in rows:
        tol_of.setdefault(mat.id, settings.tolerance_for(mat.category))
    items, devs = [], []
    by_mat: dict[int, float] = {}
    for mat, lot_no, decision, test_id, batch_id, actual, unit in rows:
        by_mat[mat.id] = by_mat.get(mat.id, 0.0) + (logic.convert(actual, unit, planned[mat.id][1]) or 0.0
                                                   if mat.id in planned else 0.0)
    for mat, lot_no, decision, test_id, batch_id, actual, unit in rows:
        p = planned.get(mat.id)
        plan_q = logic.convert(p[0], p[1], unit) if p else None
        items.append(dict(material_id=mat.id, material_name=mat.name, lot_no=lot_no, lot_decision=decision,
                          lot_test_id=test_id, batch_id=batch_id, planned=plan_q, actual=actual, unit=unit, dev_pct=None,
                          tolerance_pct=tol_of.get(mat.id)))
    # Deviation per material (a material may come from two lots): total packed vs planned.
    for mid, (q, u) in planned.items():
        dev = logic.deviation_pct(q, by_mat.get(mid, 0.0))
        devs.append((dev, tol_of.get(mid)))
        for it in items:
            if it["material_id"] == mid:
                it["dev_pct"] = dev
    missing = [mid for mid in planned if by_mat.get(mid, 0.0) == 0.0]
    status, largest = logic.item_status(devs)
    tol = logic.single_tolerance(t for _, t in devs) if devs else None
    lot_issue = any(r[2] != "Accepted" for r in rows)
    net = sum(logic.convert(r[5], r[6], "kg") or 0.0 for r in rows if logic.unit_kind(r[6]) == "mass") or None
    if not remarks:
        why = []
        if lot_issue:
            why.append("lots that are not accepted")
        if status == "over":
            why.append("quantities outside the batching tolerance")
        if missing:
            why.append("materials of the mix design missing")
        if why:
            raise ValidationError([f"Add a remark to pack with {', '.join(why)}."])

    packs = []
    for _ in range(copies):
        pk = Pack(pack_no=_next_no(db, Pack.pack_no, f"BAG-{pdate:%Y%m%d}-", 4), kind=kind, pack_date=pdate,
                  order_id=order.id, recipe_id=order.recipe_id, recipe_name=order.recipe.name if order.recipe else "",
                  net_kg=net, gross_kg=gross, tolerance_pct=tol, max_abs_dev_pct=largest, batching_status=status,
                  lot_issue=lot_issue, status="Packed", remarks=remarks, created_by_id=user.id,
                  items=[PackItem(**it) for it in items])
        db.add(pk)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise ValidationError(["Another bag was saved at the same moment. Save again."])
        packs.append(pk)
    audit.record(db, user, "create", "pack", packs[0].pack_no, {
        "kind": kind, "order": order.order_no, "copies": copies, "last": packs[-1].pack_no,
        "items": [(r[0].name, r[1], r[5], r[6]) for r in rows]})
    db.commit()
    return packs


def flagged(pack: Pack) -> bool:
    return pack.lot_issue or pack.batching_status == "over"


# ---------------------------------------------------------------- site mixing

def save_site_mix(db: Session, user: User, disp: Dispatch, form) -> SiteMix:
    """form: mix_date, started_at, finished_at, element, volume_m3, water_l, mixing_time_min, slump_mm, flow_mm,
    concrete_temp_c, ambient_temp_c, supervisor, cube_sample_id, remarks, pack_ids=[...],
    admixtures=[{pack_id, dose, unit}]"""
    errors: list[str] = []
    mdate = parse_date(form.get("mix_date"), "mixing date", errors)
    started = _parse_dt(form.get("started_at"), "Start time", errors)
    finished = _parse_dt(form.get("finished_at"), "Finish time", errors)
    if started and finished and finished < started:
        errors.append("Finish time is before the start time.")
    nums = {}
    for name, label in (("volume_m3", "Volume mixed"), ("water_l", "Water added"), ("mixing_time_min", "Mixing time"),
                        ("slump_mm", "Slump"), ("flow_mm", "Flow"), ("concrete_temp_c", "Concrete temperature"),
                        ("ambient_temp_c", "Ambient temperature")):
        nums[name] = parse_num(form.get(name), label, errors)
    on_truck = {p.id: p for p in db.scalars(select(Pack).where(Pack.dispatch_id == disp.id)).all()}
    chosen = []
    for raw in form.get("pack_ids") or []:
        pk = on_truck.get(_int_or_none(raw) or 0)
        if not pk:
            errors.append("A selected bag is not on this dispatch.")
            continue
        if pk.kind == "Admixture barrel":
            continue
        if pk.status != "Loaded":
            errors.append(f"{pk.pack_no} is {pk.status.lower()}; only loaded bags can be used.")
            continue
        chosen.append(pk)
    adm = []
    for i, it in enumerate(form.get("admixtures") or [], start=1):
        pid = _int_or_none(it.get("pack_id"))
        if not pid and not str(it.get("dose") or "").strip():
            continue
        pk = on_truck.get(pid or 0)
        if not pk or pk.kind != "Admixture barrel":
            errors.append(f"Admixture line {i}: select a barrel loaded on this dispatch.")
            continue
        dose = parse_num(it.get("dose"), f"Admixture line {i} dose", errors)
        unit = str(it.get("unit") or "kg")
        if dose is None or dose <= 0:
            errors.append(f"Admixture line {i}: enter the dose used.")
            continue
        if unit not in ("kg", "L"):
            errors.append(f"Admixture line {i}: unit must be kg or L.")
            continue
        adm.append((pk, dose, unit))
    if not chosen and not errors:
        errors.append("Tick the bags that were mixed.")
    cube = None
    if form.get("cube_sample_id"):
        cube = db.get(CubeSample, _int_or_none(form.get("cube_sample_id")) or 0)
        if not cube or cube.dispatch_id != disp.id:
            errors.append("The cube sample must belong to this dispatch.")
    if errors:
        raise ValidationError(errors)
    mix = SiteMix(mix_no=_next_no(db, SiteMix.mix_no, f"SM-{mdate:%Y%m%d}-", 3), dispatch_id=disp.id, mix_date=mdate,
                  started_at=started, finished_at=finished, element=_s(form, "element"), supervisor=_s(form, "supervisor"),
                  cube_sample_id=cube.id if cube else None, remarks=_s(form, "remarks"), created_by_id=user.id,
                  admixtures=[SiteMixAdmixture(pack_id=pk.id, dose=d, unit=u) for pk, d, u in adm], **nums)
    db.add(mix)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValidationError(["Another record was saved at the same moment. Save again."])
    for pk in chosen:
        pk.site_mix_id, pk.status = mix.id, "Used at site"
    audit.record(db, user, "create", "site_mix", mix.mix_no, {
        "dispatch": disp.dispatch_no, "bags": [p.pack_no for p in chosen],
        "admixture": [(p.pack_no, d, u) for p, d, u in adm], "water_l": nums["water_l"]})
    db.commit()
    return mix


def mix_summary(mix: SiteMix) -> dict:
    """Totals from the bags used. Water is taken as 1 kg per litre for the water/binder ratio."""
    binder = aggregate = 0.0
    unknown = False
    for pk in mix.packs:
        for it in pk.items:
            kg = logic.convert(it.actual, it.unit, "kg")
            if kg is None:
                unknown = True
                continue
            if pk.kind == "Cementitious jumbo bag":
                binder += kg
            elif pk.kind == "Aggregate jumbo bag":
                aggregate += kg
    wb = round(mix.water_l / binder, 3) if mix.water_l is not None and binder else None
    return {"binder_kg": binder, "aggregate_kg": aggregate, "wb": wb, "unknown_units": unknown}


# ---------------------------------------------------------------- AI review data

def _num(x, nd=2):
    return round(x, nd) if isinstance(x, (int, float)) else x


def review_data(db: Session, date_from, date_to, limit: int) -> dict:
    """Coating and grinding batches, bags and site mixing records in the period, for the AI review.

    Only stored values are sent; nothing is derived except the bag totals and water/binder ratio of a site mix,
    which are labelled with how they were calculated."""
    batches = db.scalars(select(ProcessBatch).where(ProcessBatch.batch_date >= date_from, ProcessBatch.batch_date <= date_to)
                         .options(selectinload(ProcessBatch.inputs)).order_by(ProcessBatch.batch_date.desc())
                         .limit(limit)).all()
    tests = {}
    tids = [b.qc_test_id for b in batches if b.qc_test_id]
    if tids:
        tests = {t.id: t for t in db.scalars(select(QCTest).where(QCTest.id.in_(tids))).all()}

    def batch_row(b: ProcessBatch) -> dict:
        t = tests.get(b.qc_test_id)
        row = {"batch_no": b.batch_no, "date": b.batch_date.isoformat(), "shift": b.shift or None,
               "equipment": b.equipment.name if b.equipment else None,
               "output": {"material": b.output_material_name, "lot_no": b.output_lot_no, "qty": b.output_qty,
                          "unit": b.output_unit},
               "decision": b.decision, "used_lots_not_accepted": b.lot_issue, "remarks": b.remarks or None,
               "qc_test": ({"test_no": t.test_no, "overall": t.overall, "decision": t.decision} if t else None),
               "inputs": [{"role": i.role, "material": i.material_name, "lot_no": i.lot_no or None,
                           "lot_decision": i.lot_decision or "no QC record", "qty": i.qty, "unit": i.unit}
                          for i in b.inputs]}
        if b.kind == "coating":
            row["coating_pct_of_aggregate_mass"] = b.coating_pct
            row["coating_target_pct"] = b.coating_target_pct
            row["coating_mass_deviation_from_target_pct"] = _num(b.coating_dev_pct)
            row["coating_tolerance_pct"] = b.coating_tol_pct
            row["coating_check"] = {"ok": "within tolerance", "over": "outside tolerance", "notol": "no tolerance set",
                                    "notarget": "no target set for this coated material"}.get(b.coating_status or "", None)
        else:
            row["blaine_m2_per_kg_entered"] = b.blaine_m2kg
            row["residue_45_micron_pct_entered"] = b.residue45_pct
        return row

    packs = db.scalars(select(Pack).where(Pack.pack_date >= date_from, Pack.pack_date <= date_to)
                       .options(selectinload(Pack.items), selectinload(Pack.order), selectinload(Pack.dispatch),
                                selectinload(Pack.site_mix))
                       .order_by(Pack.pack_date.desc(), Pack.pack_no.desc()).limit(limit)).all()
    bnos = {b.id: b.batch_no for b in db.scalars(select(ProcessBatch).where(
        ProcessBatch.id.in_({it.batch_id for p in packs for it in p.items if it.batch_id}))).all()} if packs else {}
    bdec = {b.batch_no: b.decision for b in batches}
    counts: dict[str, dict[str, int]] = {}
    for p in packs:
        counts.setdefault(p.kind, {}).setdefault(p.status, 0)
        counts[p.kind][p.status] += 1

    def pack_row(p: Pack) -> dict:
        return {"pack_no": p.pack_no, "kind": p.kind, "date": p.pack_date.isoformat(), "order_no": p.order.order_no,
                "mix_design": p.recipe_name or None, "net_kg": _num(p.net_kg), "tolerance_pct": p.tolerance_pct,
                "largest_deviation_pct": _num(p.max_abs_dev_pct),
                "batching_check": {"ok": "within tolerance", "over": "outside tolerance", "notol": "no tolerance set",
                                   "nodata": "no planned quantities"}.get(p.batching_status, p.batching_status),
                "used_lots_not_accepted": p.lot_issue, "status": p.status,
                "dispatch_no": p.dispatch.dispatch_no if p.dispatch else None,
                "site_mix_no": p.site_mix.mix_no if p.site_mix else None, "remarks": p.remarks or None,
                "contents": [{"material": it.material_name, "lot_no": it.lot_no or None,
                              "lot_decision": it.lot_decision or "no QC record",
                              "from_batch": bnos.get(it.batch_id), "batch_decision": bdec.get(bnos.get(it.batch_id)),
                              "planned": _num(it.planned), "actual": it.actual, "unit": it.unit,
                              "deviation_pct": _num(it.dev_pct), "tolerance_pct": it.tolerance_pct}
                             for it in p.items]}

    mixes = db.scalars(select(SiteMix).where(SiteMix.mix_date >= date_from, SiteMix.mix_date <= date_to)
                       .options(selectinload(SiteMix.packs).selectinload(Pack.items),
                                selectinload(SiteMix.admixtures).selectinload(SiteMixAdmixture.pack).selectinload(Pack.items))
                       .order_by(SiteMix.mix_date.desc()).limit(limit)).all()

    def mix_row(m: SiteMix) -> dict:
        s = mix_summary(m)
        d = m.dispatch
        return {"mix_no": m.mix_no, "date": m.mix_date.isoformat(), "dispatch_no": d.dispatch_no,
                "order_no": d.order.order_no, "customer": d.order.customer.name, "element": m.element or None,
                "volume_m3": m.volume_m3, "water_l": m.water_l, "mixing_time_min": m.mixing_time_min,
                "slump_mm": m.slump_mm, "flow_mm": m.flow_mm, "concrete_temp_c": m.concrete_temp_c,
                "ambient_temp_c": m.ambient_temp_c, "supervisor": m.supervisor or None, "remarks": m.remarks or None,
                "cube_sample_no": m.cube_sample.sample_no if m.cube_sample else None,
                "bags_used": [{"pack_no": p.pack_no, "kind": p.kind, "flagged": flagged(p)} for p in m.packs],
                "admixture_doses": [{"pack_no": a.pack.pack_no,
                                     "product": ", ".join(it.material_name for it in a.pack.items) or None,
                                     "dose": a.dose, "unit": a.unit} for a in m.admixtures],
                "binder_kg_from_bags": _num(s["binder_kg"], 1), "aggregate_kg_from_bags": _num(s["aggregate_kg"], 1),
                "water_binder_ratio": s["wb"],
                "water_binder_basis": "water litres taken as kg, divided by the cementitious bag contents used",
                "bag_units_not_convertible": s["unknown_units"]}

    return {
        "coating_batches": [batch_row(b) for b in batches if b.kind == "coating"],
        "grinding_batches": [batch_row(b) for b in batches if b.kind == "grinding"],
        "bag_counts_by_kind_and_status": counts,
        "bags": [pack_row(p) for p in packs],
        "site_mixes": [mix_row(m) for m in mixes],
    }
