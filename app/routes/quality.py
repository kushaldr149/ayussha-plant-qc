"""Non-conformance reports and equipment calibration."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import config
from .. import operations as ops
from ..db import get_db
from ..models import CAL_RESULTS, NCR, NCR_SOURCES, NCR_STATUSES, CubeSample, Dispatch, Equipment, ProductionRecord, QCTest, User
from ..security import can, check_csrf, require
from ..services import ValidationError
from ..web import flash, redirect, render

router = APIRouter(dependencies=[Depends(check_csrf)])


# ================================================================ NCR

@router.get("/ncr")
def ncr_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    f = dict(request.query_params)
    stmt = select(NCR)
    if f.get("status") == "open":
        stmt = stmt.where(NCR.status != "Closed")
    elif f.get("status"):
        stmt = stmt.where(NCR.status == f["status"])
    if f.get("source"):
        stmt = stmt.where(NCR.source == f["source"])
    if f.get("q"):
        like = f"%{f['q'].strip().lower()}%"
        stmt = stmt.where(or_(func.lower(NCR.ncr_no).like(like), func.lower(NCR.title).like(like),
                              func.lower(NCR.description).like(like)))
    try:
        page = max(1, int(f.get("page", 1)))
    except ValueError:
        page = 1
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.options(selectinload(NCR.owner)).order_by(NCR.raised_date.desc(), NCR.id.desc())
                      .offset((page - 1) * config.PAGE_SIZE).limit(config.PAGE_SIZE)).all()
    return render(request, db, user, "ncr_list.html", rows=rows, f=f, sources=NCR_SOURCES, statuses=NCR_STATUSES,
                  page=page, pages=max(1, -(-total // config.PAGE_SIZE)), total=total, now=config.local_today())


def _users(db: Session):
    return db.scalars(select(User).where(User.active.is_(True)).order_by(User.full_name, User.username)).all()


def _link_labels(db: Session, form) -> list[str]:
    out = []
    for key, model, attr, label in (("qc_test_id", QCTest, "test_no", "Material test"),
                                    ("production_id", ProductionRecord, "record_no", "Production record"),
                                    ("dispatch_id", Dispatch, "dispatch_no", "Dispatch"),
                                    ("cube_sample_id", CubeSample, "sample_no", "Strength sample")):
        v = str(form.get(key) or "")
        if v.isdigit():
            obj = db.get(model, int(v))
            if obj:
                out.append(f"{label} {getattr(obj, attr)}")
    return out


@router.get("/ncr/new")
def ncr_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("ncr.raise"))):
    form = {k: request.query_params.get(k, "") for k in ("qc_test_id", "production_id", "dispatch_id", "cube_sample_id", "source")}
    return render(request, db, user, "ncr_form.html", n=None, form=form, users=_users(db), sources=NCR_SOURCES,
                  statuses=NCR_STATUSES, links=_link_labels(db, form))


@router.post("/ncr/new")
async def ncr_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("ncr.raise"))):
    form = await request.form()
    try:
        n = ops.save_ncr(db, user, form, None, can_manage=can(user, "ncr.manage"))
    except ValidationError as e:
        return render(request, db, user, "ncr_form.html", status_code=400, n=None, form=form, users=_users(db),
                      sources=NCR_SOURCES, statuses=NCR_STATUSES, links=_link_labels(db, form), errors=e.messages)
    flash(request, f"{n.ncr_no} raised.")
    return redirect(f"/ncr/{n.id}")


def _ncr(db: Session, nid: int) -> NCR:
    n = db.get(NCR, nid)
    if not n:
        raise HTTPException(404, "This NCR does not exist.")
    return n


@router.get("/ncr/{nid}")
def ncr_detail(nid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return render(request, db, user, "ncr_detail.html", n=_ncr(db, nid), form={}, users=_users(db),
                  statuses=NCR_STATUSES, now=config.local_today())


@router.post("/ncr/{nid}")
async def ncr_update(nid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("ncr.manage"))):
    n = _ncr(db, nid)
    form = await request.form()
    try:
        ops.save_ncr(db, user, form, n, can_manage=True)
    except ValidationError as e:
        db.rollback()
        return render(request, db, user, "ncr_detail.html", status_code=400, n=_ncr(db, nid), form=form,
                      users=_users(db), statuses=NCR_STATUSES, now=config.local_today(), errors=e.messages)
    flash(request, f"{n.ncr_no} updated.")
    return redirect(f"/ncr/{n.id}")


# ================================================================ equipment

@router.get("/equipment")
def equipment_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    rows = db.scalars(select(Equipment).options(selectinload(Equipment.calibrations))
                      .order_by(Equipment.next_due.is_(None), Equipment.next_due, Equipment.tag)).all()
    return render(request, db, user, "equipment_list.html", rows=rows, now=config.local_today())


@router.get("/equipment/new")
def equipment_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("equipment.write"))):
    return render(request, db, user, "equipment_form.html", e=None, form={}, statuses=ops.EQUIPMENT_STATUSES)


@router.post("/equipment/new")
async def equipment_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("equipment.write"))):
    form = await request.form()
    try:
        e = ops.save_equipment(db, user, form)
    except ValidationError as err:
        return render(request, db, user, "equipment_form.html", status_code=400, e=None, form=form,
                      statuses=ops.EQUIPMENT_STATUSES, errors=err.messages)
    flash(request, f"Equipment {e.tag} saved.")
    return redirect(f"/equipment/{e.id}")


def _eq(db: Session, eid: int) -> Equipment:
    e = db.get(Equipment, eid)
    if not e:
        raise HTTPException(404, "This equipment does not exist.")
    return e


@router.get("/equipment/{eid}")
def equipment_detail(eid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return render(request, db, user, "equipment_detail.html", e=_eq(db, eid), form={}, cal_form={},
                  statuses=ops.EQUIPMENT_STATUSES, results=CAL_RESULTS, now=config.local_today())


@router.post("/equipment/{eid}")
async def equipment_update(eid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("equipment.write"))):
    e = _eq(db, eid)
    form = await request.form()
    try:
        ops.save_equipment(db, user, form, e)
    except ValidationError as err:
        db.rollback()
        return render(request, db, user, "equipment_detail.html", status_code=400, e=_eq(db, eid), form=form, cal_form={},
                      statuses=ops.EQUIPMENT_STATUSES, results=CAL_RESULTS, now=config.local_today(), errors=err.messages)
    flash(request, f"Equipment {e.tag} updated.")
    return redirect(f"/equipment/{e.id}")


@router.post("/equipment/{eid}/calibration")
async def equipment_calibration(eid: int, request: Request, db: Session = Depends(get_db),
                                user: User = Depends(require("equipment.write"))):
    e = _eq(db, eid)
    form = await request.form()
    try:
        ops.add_calibration(db, user, e, form)
    except ValidationError as err:
        return render(request, db, user, "equipment_detail.html", status_code=400, e=e, form={}, cal_form=form,
                      statuses=ops.EQUIPMENT_STATUSES, results=CAL_RESULTS, now=config.local_today(), errors=err.messages)
    flash(request, "Calibration recorded.")
    return redirect(f"/equipment/{e.id}")
