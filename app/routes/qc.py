"""Inward material QC: list, new test, detail, decision change, delete."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import audit, config, services
from ..db import get_db
from ..models import Material, ProductionComponent, QCTest, User
from ..security import check_csrf, require
from ..web import flash, redirect, render

router = APIRouter(prefix="/qc", dependencies=[Depends(check_csrf)])


def qc_query(params: dict):
    stmt = select(QCTest)
    if params.get("material"):
        try:
            stmt = stmt.where(QCTest.material_id == int(params["material"]))
        except ValueError:
            pass
    if params.get("decision"):
        stmt = stmt.where(QCTest.decision == params["decision"])
    if params.get("result"):
        stmt = stmt.where(QCTest.overall == params["result"])
    if params.get("q"):
        like = f"%{params['q'].strip().lower()}%"
        stmt = stmt.where(or_(
            func.lower(QCTest.lot_no).like(like), func.lower(QCTest.vehicle_no).like(like),
            func.lower(QCTest.supplier).like(like), func.lower(QCTest.test_no).like(like),
            func.lower(QCTest.material_name).like(like)))
    from datetime import date
    for key, op in (("from", ">="), ("to", "<=")):
        if params.get(key):
            try:
                d = date.fromisoformat(params[key])
                stmt = stmt.where(QCTest.test_date >= d if op == ">=" else QCTest.test_date <= d)
            except ValueError:
                pass
    return stmt


@router.get("")
def qc_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    params = dict(request.query_params)
    try:
        page = max(1, int(params.get("page", 1)))
    except ValueError:
        page = 1
    stmt = qc_query(params)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    tests = db.scalars(
        stmt.options(selectinload(QCTest.results), selectinload(QCTest.created_by))
        .order_by(QCTest.test_date.desc(), QCTest.id.desc())
        .offset((page - 1) * config.PAGE_SIZE).limit(config.PAGE_SIZE)
    ).all()
    materials = db.scalars(select(Material).order_by(Material.name)).all()
    return render(request, db, user, "qc_list.html", tests=tests, materials=materials, f=params,
                  page=page, pages=max(1, -(-total // config.PAGE_SIZE)), total=total)


def _form_context(db: Session):
    materials = db.scalars(
        select(Material).where(Material.active.is_(True)).options(selectinload(Material.parameters)).order_by(Material.name)
    ).all()
    payload = {m.id: {"supplier": m.supplier, "params": [
        {"id": p.id, "name": p.name, "unit": p.unit, "min": p.min_value, "max": p.max_value, "method": p.method}
        for p in m.parameters if p.active]} for m in materials}
    return materials, payload


@router.get("/new")
def qc_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("qc.write"))):
    materials, payload = _form_context(db)
    if not materials:
        flash(request, "Add materials and their test parameters in Setup before recording tests.", "warn")
        return redirect("/setup")
    return render(request, db, user, "qc_form.html", materials=materials, payload=payload, form={})


@router.post("/new")
async def qc_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("qc.write"))):
    raw = await request.form()
    form = {k: raw.get(k, "") for k in ("test_date", "material_id", "supplier", "lot_no", "vehicle_no",
                                         "quantity", "unit", "decision", "remarks")}
    form["values"] = {k[2:]: v for k, v in raw.items() if k.startswith("p_")}
    try:
        test = services.save_qc_test(db, user, form)
    except services.ValidationError as e:
        materials, payload = _form_context(db)
        return render(request, db, user, "qc_form.html", status_code=400, materials=materials, payload=payload,
                      form=form, values=form["values"], errors=e.messages)
    flash(request, f"Test {test.test_no} saved.")
    return redirect(f"/qc/{test.id}")


def _get(db: Session, test_id: int) -> QCTest:
    test = db.scalars(select(QCTest).where(QCTest.id == test_id).options(selectinload(QCTest.results))).first()
    if not test:
        raise HTTPException(404, "This test does not exist.")
    return test


@router.get("/{test_id}")
def qc_detail(test_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    test = _get(db, test_id)
    used_in = db.scalars(
        select(ProductionComponent).where(ProductionComponent.lot_test_id == test.id).limit(100)
    ).all()
    return render(request, db, user, "qc_detail.html", t=test, used_in=used_in)


@router.post("/{test_id}/decision")
async def qc_decision(test_id: int, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require("qc.decide"))):
    test = _get(db, test_id)
    form = await request.form()
    try:
        services.change_decision(db, user, test, str(form.get("decision", "")), str(form.get("remarks", "")))
    except services.ValidationError as e:
        used_in = db.scalars(select(ProductionComponent).where(ProductionComponent.lot_test_id == test.id)).all()
        return render(request, db, user, "qc_detail.html", status_code=400, t=test, used_in=used_in, errors=e.messages)
    flash(request, "Decision saved.")
    return redirect(f"/qc/{test.id}")


@router.post("/{test_id}/delete")
def qc_delete(test_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("records.delete"))):
    test = _get(db, test_id)
    used = db.scalar(select(func.count(ProductionComponent.id)).where(ProductionComponent.lot_test_id == test.id))
    if used:
        flash(request, f"This lot is referenced by {used} production component(s), so the test cannot be deleted.", "error")
        return redirect(f"/qc/{test.id}")
    audit.record(db, user, "delete", "qc_test", test.test_no, {"material": test.material_name, "lot": test.lot_no})
    db.delete(test)
    db.commit()
    flash(request, f"Test {test.test_no} deleted.")
    return redirect("/qc")
