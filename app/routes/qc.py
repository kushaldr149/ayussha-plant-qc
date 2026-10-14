"""Inward material QC: list, new test, detail, decision change, delete."""
from __future__ import annotations

import json
import re

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
    payload = {m.id: {"supplier": m.supplier, "category": m.category, "params": [
        {"id": p.id, "name": p.name, "unit": p.unit, "min": p.min_value, "max": p.max_value, "method": p.method,
         "group": p.group_name or "", "frequency": p.frequency or "Every lot", "calc": p.calc or "",
         "type": p.value_type or "number", "sieve": p.sieve_mm, "note": p.note or ""}
        for p in m.parameters if p.active]} for m in materials}
    from .. import is_library as _lib
    calcs = {k: {"title": c.title, "method": c.method, "inputs": c.inputs, "formulas": c.formulas}
             for k, c in _lib.CALCS.items()}
    payload = {"materials": payload, "calcs": calcs}
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
    form["workings"] = {k[2:]: v for k, v in raw.items() if k.startswith("w_")}
    try:
        test = services.save_qc_test(db, user, form)
    except services.ValidationError as e:
        materials, payload = _form_context(db)
        return render(request, db, user, "qc_form.html", status_code=400, materials=materials, payload=payload,
                      form=form, values=form["values"], workings=form["workings"], errors=e.messages)
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
    return render(request, db, user, "qc_detail.html", t=test, used_in=used_in, **result_view(test), **_trace(db, test))


def _trace(db: Session, test: QCTest) -> dict:
    """Coating/grinding batches and bags that used this lot."""
    from ..models import Pack, PackItem, ProcessBatch, ProcessInput
    proc = db.execute(select(ProcessInput, ProcessBatch).join(ProcessBatch, ProcessBatch.id == ProcessInput.batch_id)
                      .where(ProcessInput.lot_test_id == test.id).limit(200)).all()
    packs = db.execute(select(PackItem, Pack).join(Pack, Pack.id == PackItem.pack_id)
                       .where(PackItem.lot_test_id == test.id).order_by(Pack.pack_no).limit(500)).all()
    return {"used_process": proc, "used_packs": packs}


_SIEVE_NAME = re.compile(r"^Passing (\d+(?:\.\d+)?) (mm|µm) sieve$")


def result_view(test: QCTest) -> dict:
    """Results grouped for display, parsed worksheet workings, and the IS 383 zone check for fine aggregate."""
    from .. import is_library as _lib
    groups: list[tuple[str, list]] = []
    work: dict[int, dict] = {}
    passing: dict[float, float] = {}
    crushed = False
    for r in test.results:
        g = r.group_name or "Tests"
        bucket = next((rows for name, rows in groups if name == g), None)
        if bucket is None:
            bucket = []
            groups.append((g, bucket))
        bucket.append(r)
        if r.workings:
            try:
                w = json.loads(r.workings)
                c = _lib.CALCS.get(w.get("calc", ""))
                w["title"] = c.title if c else ("Sieve analysis" if w.get("calc") == "sieve" else "")
                w["formulas"] = c.formulas if c else []
                w["labels"] = dict(c.inputs) if c else {}
                work[r.id] = w
            except (ValueError, TypeError, AttributeError):
                pass
        m = _SIEVE_NAME.match(r.name)
        if m and r.value is not None:
            mm = float(m.group(1)) / (1000 if m.group(2) == "µm" else 1)
            passing[round(mm, 3)] = r.value
            if abs(mm - 0.15) < 1e-9 and (r.max_value or 0) > 10:
                crushed = True
    zones = _lib.classify_zone(passing, crushed) if test.category == "Fine aggregate" and len(passing) >= 3 else None
    return {"groups": groups, "work": work, "zones": zones}


@router.post("/{test_id}/decision")
async def qc_decision(test_id: int, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require("qc.decide"))):
    test = _get(db, test_id)
    form = await request.form()
    try:
        services.change_decision(db, user, test, str(form.get("decision", "")), str(form.get("remarks", "")))
    except services.ValidationError as e:
        used_in = db.scalars(select(ProductionComponent).where(ProductionComponent.lot_test_id == test.id)).all()
        return render(request, db, user, "qc_detail.html", status_code=400, t=test, used_in=used_in, errors=e.messages,
                      **result_view(test), **_trace(db, test))
    flash(request, "Decision saved.")
    return redirect(f"/qc/{test.id}")


@router.post("/{test_id}/delete")
def qc_delete(test_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("records.delete"))):
    test = _get(db, test_id)
    from ..models import NCR
    used = db.scalar(select(func.count(ProductionComponent.id)).where(ProductionComponent.lot_test_id == test.id))
    from ..models import PackItem, ProcessBatch, ProcessInput
    used += (db.scalar(select(func.count(ProcessInput.id)).where(ProcessInput.lot_test_id == test.id)) or 0) + \
            (db.scalar(select(func.count(PackItem.id)).where(PackItem.lot_test_id == test.id)) or 0) + \
            (db.scalar(select(func.count(ProcessBatch.id)).where(ProcessBatch.qc_test_id == test.id)) or 0)
    if db.scalar(select(func.count(NCR.id)).where(NCR.qc_test_id == test.id)):
        flash(request, "An NCR refers to this test, so it cannot be deleted.", "error")
        return redirect(f"/qc/{test.id}")
    if used:
        flash(request, f"This lot is referenced by {used} production, process or bag record(s), so the test cannot be deleted.", "error")
        return redirect(f"/qc/{test.id}")
    audit.record(db, user, "delete", "qc_test", test.test_no, {"material": test.material_name, "lot": test.lot_no})
    db.delete(test)
    db.commit()
    flash(request, f"Test {test.test_no} deleted.")
    return redirect("/qc")


# ---------------------------------------------------------------- worksheets

from fastapi.responses import JSONResponse  # noqa: E402

from .. import is_library as lib  # noqa: E402


@router.post("/calc")
async def qc_calc(request: Request, user: User = Depends(require("qc.write"))):
    """Run an IS 2386 worksheet. Form: calc=<key>, in_<name>=<value> ...; sieve: r_<mm>=<g>, total=<g>, crushed."""
    form = await request.form()
    key = str(form.get("calc", ""))
    try:
        if key == "sieve":
            retained = {}
            for k, v in form.items():
                if k.startswith("r_") and str(v).strip() != "":
                    retained[float(k[2:])] = float(str(v).replace(",", ""))
            total_raw = str(form.get("total", "")).strip()
            res = lib.sieve_analysis(retained, float(total_raw) if total_raw else None)
            out = {"passing": {f"{s:g}": p for s, p in res["passing"].items()}, "fm": res["fm"],
                   "total": res["total"], "fm_sieves": [f"{s:g}" for s in res["fm_sieves"]]}
            if form.get("fine") == "1":
                out["zones"] = lib.classify_zone(res["passing"], crushed=form.get("crushed") == "1")
            return JSONResponse({"ok": True, "result": out})
        if key not in lib.CALCS:
            raise ValueError("Unknown worksheet.")
        values = {}
        for name, _label in lib.CALCS[key].inputs:
            raw = str(form.get("in_" + name, "")).strip().replace(",", "")
            if raw:
                values[name] = float(raw)
        return JSONResponse({"ok": True, "result": lib.run_calc(key, values)})
    except ValueError as e:
        msg = str(e)
        if msg.startswith("could not convert"):
            msg = "Enter numbers only."
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
