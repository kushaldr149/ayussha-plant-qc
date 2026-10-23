"""Concrete strength tests: specimens cast from deliveries and their results."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import audit, config
from .. import operations as ops
from ..db import get_db
from ..models import NCR, ConcreteGrade, CubeSample, Dispatch, Order, User
from ..security import check_csrf, require
from ..services import ValidationError
from ..web import flash, indexed_rows, redirect, render

router = APIRouter(prefix="/strength", dependencies=[Depends(check_csrf)])


def _dctx(db: Session, s: CubeSample, dform=None) -> dict:
    from .. import durability as du
    from ..models import DURABILITY_TESTS
    line = du.product_line_of(s)
    targets = {k: du.target_for(db, k, line) for k in DURABILITY_TESTS if k != "other"}
    return {"dura": du.results_for(db, s.id), "DTESTS": DURABILITY_TESTS, "dlabels": du.RESULT_LABELS,
            "dtargets": targets, "dline": line, "dform": dform or {}}


@router.get("")
def strength_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    f = dict(request.query_params)
    stmt = select(CubeSample)
    if f.get("grade"):
        try:
            stmt = stmt.where(CubeSample.grade_id == int(f["grade"]))
        except ValueError:
            pass
    for key in ("from", "to"):
        if f.get(key):
            try:
                d = date.fromisoformat(f[key])
                stmt = stmt.where(CubeSample.cast_date >= d if key == "from" else CubeSample.cast_date <= d)
            except ValueError:
                pass
    if f.get("q"):
        like = f"%{f['q'].strip().lower()}%"
        stmt = stmt.outerjoin(Dispatch).where(or_(func.lower(CubeSample.sample_no).like(like),
                                                  func.lower(Dispatch.dispatch_no).like(like),
                                                  func.lower(CubeSample.cast_location).like(like)))
    try:
        page = max(1, int(f.get("page", 1)))
    except ValueError:
        page = 1
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    samples = db.scalars(stmt.options(selectinload(CubeSample.results), selectinload(CubeSample.grade),
                                      selectinload(CubeSample.dispatch).selectinload(Dispatch.order).selectinload(Order.customer))
                         .order_by(CubeSample.cast_date.desc(), CubeSample.id.desc())
                         .offset((page - 1) * config.PAGE_SIZE).limit(config.PAGE_SIZE)).all()
    rows = [(s, ops.sample_summary(s)) for s in samples]
    due = ops.due_tests(db, config.local_today())
    grades = db.scalars(select(ConcreteGrade).order_by(ConcreteGrade.name)).all()
    return render(request, db, user, "strength_list.html", rows=rows, due=due, grades=grades, f=f, page=page,
                  pages=max(1, -(-total // config.PAGE_SIZE)), total=total)


def _ctx(db: Session) -> dict:
    grades = db.scalars(select(ConcreteGrade).where(ConcreteGrade.active.is_(True)).order_by(ConcreteGrade.name)).all()
    dispatches = db.scalars(select(Dispatch).where(Dispatch.status.in_(("Dispatched", "Delivered")))
                            .options(selectinload(Dispatch.order).selectinload(Order.customer),
                                     selectinload(Dispatch.order).selectinload(Order.site))
                            .order_by(Dispatch.dispatch_date.desc()).limit(200)).all()
    return {"grades": grades, "dispatches": dispatches}


@router.get("/new")
def sample_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("strength.write"))):
    pre = {"dispatch_id": request.query_params.get("dispatch", "")}
    if pre["dispatch_id"]:
        d = db.get(Dispatch, int(pre["dispatch_id"])) if pre["dispatch_id"].isdigit() else None
        if d and d.order.grade_id:
            pre["grade_id"] = str(d.order.grade_id)
        if d and d.order.site:
            pre["cast_location"] = d.order.site.name
    return render(request, db, user, "strength_form.html", form=pre, **_ctx(db))


@router.post("/new")
async def sample_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("strength.write"))):
    form = await request.form()
    try:
        s = ops.save_sample(db, user, form)
    except ValidationError as e:
        return render(request, db, user, "strength_form.html", status_code=400, form=form, errors=e.messages, **_ctx(db))
    flash(request, f"Sample {s.sample_no} saved.")
    return redirect(f"/strength/{s.id}")


def _get(db: Session, sid: int) -> CubeSample:
    s = db.scalars(select(CubeSample).where(CubeSample.id == sid).options(selectinload(CubeSample.results))).first()
    if not s:
        raise HTTPException(404, "This sample does not exist.")
    return s


@router.get("/{sid}")
def sample_detail(sid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    s = _get(db, sid)
    ncrs = db.scalars(select(NCR).where(NCR.cube_sample_id == s.id)).all()
    summary = ops.sample_summary(s)
    next_age = next((g["age"] for g in summary["groups"] if not g["results"]), "")
    return render(request, db, user, "strength_detail.html", s=s, summary=summary, ncrs=ncrs, form={"age_days": next_age},
                  rows=[{}] * (s.specimens_per_age or 3), **_dctx(db, s))


@router.post("/{sid}/results")
async def sample_results(sid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("strength.write"))):
    s = _get(db, sid)
    raw = await request.form()
    form = {"age_days": raw.get("age_days", ""), "test_date": raw.get("test_date", ""),
            "rows": indexed_rows(raw, "r", ["specimen_no", "mass_kg", "load_kn", "strength_mpa"])}
    try:
        ops.add_results(db, user, s, form)
    except ValidationError as e:
        ncrs = db.scalars(select(NCR).where(NCR.cube_sample_id == s.id)).all()
        return render(request, db, user, "strength_detail.html", status_code=400, s=s, summary=ops.sample_summary(s),
                      ncrs=ncrs, form=form, rows=form["rows"] or [{}], errors=e.messages, **_dctx(db, s))
    flash(request, "Results saved.")
    return redirect(f"/strength/{s.id}")


@router.post("/{sid}/durability")
async def sample_durability(sid: int, request: Request, db: Session = Depends(get_db),
                            user: User = Depends(require("strength.write"))):
    from .. import durability as du
    s = _get(db, sid)
    form = await request.form()
    try:
        r = du.add_result(db, user, s, form)
    except ValidationError as e:
        db.rollback()
        s = _get(db, sid)
        ncrs = db.scalars(select(NCR).where(NCR.cube_sample_id == s.id)).all()
        return render(request, db, user, "strength_detail.html", status_code=400, s=s, summary=ops.sample_summary(s),
                      ncrs=ncrs, form={}, rows=[{}] * (s.specimens_per_age or 3), errors=e.messages, **_dctx(db, s, form))
    flash(request, f"{r.test_name}: mean {r.mean_value:g} {r.unit}, {du.RESULT_LABELS[r.result].lower()}.",
          "warn" if r.result == "fail" else "ok")
    return redirect(f"/strength/{s.id}#durability")


@router.post("/{sid}/results/{rid}/delete")
def result_delete(sid: int, rid: int, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require("records.delete"))):
    s = _get(db, sid)
    r = next((r for r in s.results if r.id == rid), None)
    if not r:
        raise HTTPException(404, "Not found.")
    audit.record(db, user, "delete", "cube_result", s.sample_no, {"age": r.age_days, "strength": r.strength_mpa})
    s.results.remove(r)
    db.commit()
    flash(request, "Result deleted.")
    return redirect(f"/strength/{s.id}")
