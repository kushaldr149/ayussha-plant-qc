"""Plant process: coating, grinding, packing (bags and barrels with QR labels) and site mixing."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import audit, config, process, reports, services
from ..db import get_db
from ..models import (
    DECISIONS, PACK_KINDS, PACK_STATUSES, PROCESS_KINDS, CubeSample, Dispatch, Order, Pack, PackItem, ProcessBatch,
    QCTest, SiteMix, User,
)
from ..security import check_csrf, require
from ..services import ValidationError
from ..web import flash, indexed_rows, redirect, render

router = APIRouter(dependencies=[Depends(check_csrf)])
INPUT_LINES = 6
PACK_LINES = 8


# ================================================================ overview

@router.get("/process")
def process_home(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    batches = db.scalars(select(ProcessBatch).order_by(ProcessBatch.batch_date.desc(), ProcessBatch.id.desc()).limit(15)).all()
    packs = db.scalars(select(Pack).options(selectinload(Pack.order).selectinload(Order.customer))
                       .order_by(Pack.pack_date.desc(), Pack.id.desc()).limit(15)).all()
    mixes = db.scalars(select(SiteMix).options(selectinload(SiteMix.dispatch).selectinload(Dispatch.order))
                       .order_by(SiteMix.mix_date.desc(), SiteMix.id.desc()).limit(10)).all()
    counts = dict(db.execute(select(Pack.status, func.count(Pack.id)).group_by(Pack.status)).all())
    on_hold = db.scalar(select(func.count(ProcessBatch.id)).where(ProcessBatch.decision == "On hold")) or 0
    return render(request, db, user, "process_home.html", batches=batches, packs=packs, mixes=mixes, counts=counts,
                  on_hold=on_hold, PACK_STATUSES=PACK_STATUSES, PROCESS_KINDS=PROCESS_KINDS)


# ================================================================ coating and grinding

@router.get("/process/batches")
def batch_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    f = dict(request.query_params)
    stmt = select(ProcessBatch)
    if f.get("kind") in PROCESS_KINDS:
        stmt = stmt.where(ProcessBatch.kind == f["kind"])
    if f.get("decision") in DECISIONS:
        stmt = stmt.where(ProcessBatch.decision == f["decision"])
    if f.get("q"):
        like = f"%{f['q'].strip().lower()}%"
        stmt = stmt.where(or_(func.lower(ProcessBatch.batch_no).like(like),
                              func.lower(ProcessBatch.output_material_name).like(like)))
    rows = db.scalars(stmt.options(selectinload(ProcessBatch.inputs))
                      .order_by(ProcessBatch.batch_date.desc(), ProcessBatch.id.desc()).limit(300)).all()
    return render(request, db, user, "batch_list.html", rows=rows, f=f, PROCESS_KINDS=PROCESS_KINDS)


@router.get("/process/{kind}/new")
def batch_new(kind: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require("process.write"))):
    if kind not in PROCESS_KINDS:
        raise HTTPException(404, "Not found.")
    o = process.process_options(db, kind)
    if not o["outputs"]:
        flash(request, f"Add the output material first: Setup → Add material, category {o['output_category']} "
                       "(or Add standard materials → In-house products).", "warn")
    return render(request, db, user, "batch_form.html", o=o, form={}, inputs=[], lines=INPUT_LINES)


@router.post("/process/{kind}/new")
async def batch_create(kind: str, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(require("process.write"))):
    if kind not in PROCESS_KINDS:
        raise HTTPException(404, "Not found.")
    raw = await request.form()
    form = {k: raw.get(k, "") for k in ("batch_date", "shift", "equipment_id", "output_material_id", "output_qty",
                                         "output_unit", "blaine", "residue45", "remarks")}
    form["inputs"] = indexed_rows(raw, "in", ["role", "lot", "qty", "unit"])
    try:
        b = process.save_process_batch(db, user, kind, form)
    except ValidationError as e:
        return render(request, db, user, "batch_form.html", status_code=400, o=process.process_options(db, kind),
                      form=form, inputs=form["inputs"], lines=max(INPUT_LINES, len(form["inputs"])), errors=e.messages)
    flash(request, f"{PROCESS_KINDS[kind]} batch {b.batch_no} saved. Its output lot is on hold until a decision is made.")
    return redirect(f"/process/batches/{b.id}")


def _batch(db: Session, bid: int) -> ProcessBatch:
    b = db.scalars(select(ProcessBatch).where(ProcessBatch.id == bid).options(selectinload(ProcessBatch.inputs))).first()
    if not b:
        raise HTTPException(404, "This batch does not exist.")
    return b


def _batch_ctx(db: Session, b: ProcessBatch) -> dict:
    tests = db.scalars(select(QCTest).where(QCTest.material_id == b.output_material_id)
                       .order_by(QCTest.test_date.desc()).limit(50)).all()
    used = db.scalars(select(PackItem).where(PackItem.batch_id == b.id).options(selectinload(PackItem.pack))).all()
    return {"b": b, "tests": tests, "used": used, "roles": process.ROLE_LABELS, "PROCESS_KINDS": PROCESS_KINDS}


@router.get("/process/batches/{bid}")
def batch_detail(bid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    b = _batch(db, bid)
    return render(request, db, user, "batch_detail.html", **_batch_ctx(db, b))


@router.post("/process/batches/{bid}/decision")
async def batch_decision(bid: int, request: Request, db: Session = Depends(get_db),
                         user: User = Depends(require("process.decide"))):
    b = _batch(db, bid)
    form = await request.form()
    try:
        process.set_batch_decision(db, user, b, form)
    except ValidationError as e:
        return render(request, db, user, "batch_detail.html", status_code=400, errors=e.messages, **_batch_ctx(db, b))
    flash(request, f"Decision for {b.batch_no} saved: {b.decision}.")
    return redirect(f"/process/batches/{b.id}")


# ================================================================ packing

@router.get("/packs")
def pack_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    f = dict(request.query_params)
    stmt = select(Pack)
    if f.get("kind") in PACK_KINDS:
        stmt = stmt.where(Pack.kind == f["kind"])
    if f.get("status") in PACK_STATUSES:
        stmt = stmt.where(Pack.status == f["status"])
    if f.get("order"):
        try:
            stmt = stmt.where(Pack.order_id == int(f["order"]))
        except ValueError:
            pass
    if f.get("q"):
        like = f"%{f['q'].strip().lower()}%"
        stmt = stmt.outerjoin(PackItem).where(or_(func.lower(Pack.pack_no).like(like), func.lower(PackItem.lot_no).like(like))).distinct()
    rows = db.scalars(stmt.options(selectinload(Pack.items), selectinload(Pack.order).selectinload(Order.customer))
                      .order_by(Pack.pack_date.desc(), Pack.id.desc()).limit(500)).all()
    orders = db.scalars(select(Order).order_by(Order.order_date.desc()).limit(200)).all()
    return render(request, db, user, "pack_list.html", rows=rows, f=f, kinds=list(PACK_KINDS), statuses=PACK_STATUSES,
                  orders=orders)


def _order(db: Session, raw) -> Order | None:
    try:
        return db.get(Order, int(raw)) if raw else None
    except (TypeError, ValueError):
        return None


@router.get("/packs/new")
def pack_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("process.write"))):
    q = request.query_params
    order, kind = _order(db, q.get("order_id")), q.get("kind") if q.get("kind") in PACK_KINDS else None
    ctx = process.pack_options(db, order, kind)
    if not ctx["orders"]:
        flash(request, "Create an open customer order first: bags are packed per order.", "warn")
        return redirect("/orders")
    items = [{"lot": "", "actual": f"{qty:g}", "unit": unit, "material_id": m.id} for m, qty, unit in ctx["planned"]]
    return render(request, db, user, "pack_form.html", form={"order_id": q.get("order_id", ""), "kind": kind or ""},
                  items=items, lines=max(PACK_LINES, len(items) + 2), **ctx)


@router.post("/packs/new")
async def pack_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("process.write"))):
    raw = await request.form()
    form = {k: raw.get(k, "") for k in ("order_id", "kind", "pack_date", "copies", "gross_kg", "remarks")}
    form["items"] = indexed_rows(raw, "it", ["lot", "actual", "unit"])
    try:
        packs = process.save_packs(db, user, form)
    except ValidationError as e:
        ctx = process.pack_options(db, _order(db, form["order_id"]), form["kind"] if form["kind"] in PACK_KINDS else None)
        return render(request, db, user, "pack_form.html", status_code=400, form=form, items=form["items"],
                      lines=max(PACK_LINES, len(form["items"])), errors=e.messages, **ctx)
    if len(packs) == 1:
        flash(request, f"{packs[0].kind} {packs[0].pack_no} saved. Print its label below.")
        return redirect(f"/packs/{packs[0].id}")
    flash(request, f"{len(packs)} bags saved: {packs[0].pack_no} to {packs[-1].pack_no}.")
    return redirect(f"/packs?order={packs[0].order_id}")


def _pack(db: Session, pid: int) -> Pack:
    p = db.scalars(select(Pack).where(Pack.id == pid).options(selectinload(Pack.items))).first()
    if not p:
        raise HTTPException(404, "This bag does not exist.")
    return p


@router.get("/packs/scan")
def pack_scan(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    code = (request.query_params.get("code") or "").strip().upper()
    p = db.scalars(select(Pack).where(func.upper(Pack.pack_no) == code)).first() if code else None
    if p:
        return redirect(f"/packs/{p.id}")
    if code:
        flash(request, f"No bag or barrel with number {code}.", "error")
    return render(request, db, user, "pack_scan.html", code=code)


@router.get("/packs/{pid}")
def pack_detail(pid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    p = _pack(db, pid)
    tests = {t.id: t for t in db.scalars(select(QCTest).where(QCTest.id.in_([i.lot_test_id for i in p.items if i.lot_test_id]))).all()}
    batches = {b.id: b for b in db.scalars(select(ProcessBatch).where(ProcessBatch.id.in_([i.batch_id for i in p.items if i.batch_id]))).all()}
    return render(request, db, user, "pack_detail.html", p=p, tests=tests, batches=batches, statuses=PACK_STATUSES)


@router.post("/packs/{pid}/status")
async def pack_status(pid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("process.decide"))):
    p = _pack(db, pid)
    form = await request.form()
    status, remark = str(form.get("status", "")), str(form.get("remark", "")).strip()
    if status not in ("Packed", "Rejected") or p.status not in ("Packed", "Rejected", "Returned"):
        flash(request, "Only a bag in the plant (packed, returned or rejected) can be marked packed or rejected here.", "error")
        return redirect(f"/packs/{p.id}")
    if not remark:
        flash(request, "Enter the reason.", "error")
        return redirect(f"/packs/{p.id}")
    before = p.status
    p.status, p.dispatch_id = status, None
    p.remarks = (p.remarks + "\n" if p.remarks else "") + f"{status}: {remark}"
    audit.record(db, user, "status", "pack", p.pack_no, {"before": before, "after": status, "reason": remark})
    db.commit()
    flash(request, f"{p.pack_no} marked {status.lower()}.")
    return redirect(f"/packs/{p.id}")


def _base_url(request: Request) -> str:
    return config.PUBLIC_URL or str(request.base_url).rstrip("/")


LABEL_SIZES = {"a6": "A6 (105 × 148 mm)", "a5": "A5 (148 × 210 mm)", "a4": "A4 (210 × 297 mm)", "100x150": "100 × 150 mm"}


def _labels(request: Request, db: Session, packs: list[Pack], name: str) -> Response:
    size = request.query_params.get("size", "a6")
    if size not in LABEL_SIZES:
        size = "a6"
    pdf = reports.pack_labels_pdf(packs, services.get_settings(db), _base_url(request), size)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


@router.get("/packs/{pid}/label.pdf")
def pack_label(pid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    p = _pack(db, pid)
    return _labels(request, db, [p], p.pack_no)


@router.get("/orders/{oid}/labels.pdf")
def order_labels(oid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    o = db.get(Order, oid) or None
    if not o:
        raise HTTPException(404, "This order does not exist.")
    status = request.query_params.get("status", "Packed")
    stmt = select(Pack).where(Pack.order_id == oid).options(selectinload(Pack.items)).order_by(Pack.pack_no)
    if status in PACK_STATUSES:
        stmt = stmt.where(Pack.status == status)
    packs = db.scalars(stmt).all()
    if not packs:
        flash(request, "No bags to print for this order with that status.", "warn")
        return redirect(f"/packs?order={oid}")
    return _labels(request, db, packs, f"labels-{o.order_no}")


# ================================================================ site mixing

def _dispatch(db: Session, did) -> Dispatch | None:
    try:
        return db.get(Dispatch, int(did))
    except (TypeError, ValueError):
        return None


def _mix_ctx(db: Session, d: Dispatch) -> dict:
    packs = db.scalars(select(Pack).where(Pack.dispatch_id == d.id).options(selectinload(Pack.items))
                       .order_by(Pack.kind, Pack.pack_no)).all()
    samples = db.scalars(select(CubeSample).where(CubeSample.dispatch_id == d.id)).all()
    return {"d": d, "bags": [p for p in packs if p.kind != "Admixture barrel"],
            "barrels": [p for p in packs if p.kind == "Admixture barrel"], "samples": samples}


@router.get("/site-mix/new")
def mix_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("sitemix.write"))):
    d = _dispatch(db, request.query_params.get("dispatch_id"))
    if not d:
        flash(request, "Open the dispatch first and record site mixing from there.", "warn")
        return redirect("/dispatch")
    return render(request, db, user, "sitemix_form.html", form={}, adm=[], **_mix_ctx(db, d))


@router.post("/site-mix/new")
async def mix_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("sitemix.write"))):
    raw = await request.form()
    d = _dispatch(db, raw.get("dispatch_id"))
    if not d:
        raise HTTPException(404, "This dispatch does not exist.")
    form = {k: raw.get(k, "") for k in ("mix_date", "started_at", "finished_at", "element", "volume_m3", "water_l",
                                         "mixing_time_min", "slump_mm", "flow_mm", "concrete_temp_c", "ambient_temp_c",
                                         "supervisor", "cube_sample_id", "remarks")}
    form["pack_ids"] = raw.getlist("pack_ids")
    form["admixtures"] = indexed_rows(raw, "ad", ["pack_id", "dose", "unit"])
    try:
        mix = process.save_site_mix(db, user, d, form)
    except ValidationError as e:
        return render(request, db, user, "sitemix_form.html", status_code=400, form=form, adm=form["admixtures"],
                      errors=e.messages, **_mix_ctx(db, d))
    flash(request, f"Site mixing record {mix.mix_no} saved.")
    return redirect(f"/site-mix/{mix.id}")


@router.get("/site-mix/{mid}")
def mix_detail(mid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    mix = db.scalars(select(SiteMix).where(SiteMix.id == mid).options(
        selectinload(SiteMix.packs).selectinload(Pack.items), selectinload(SiteMix.admixtures))).first()
    if not mix:
        raise HTTPException(404, "This record does not exist.")
    return render(request, db, user, "sitemix_detail.html", mix=mix, s=process.mix_summary(mix))
