"""Production log: list, new record, detail, delete, CSV import."""
from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.datastructures import UploadFile
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import audit, config, services
from ..db import get_db
from ..models import Material, ProductionComponent, ProductionRecord, Recipe, User
from ..security import check_csrf, require
from ..web import flash, indexed_rows, redirect, render

router = APIRouter(prefix="/production", dependencies=[Depends(check_csrf)])

CSV_COLUMNS = ["date", "shift", "record_no", "product_line", "material", "lot_no", "planned", "actual",
               "unit", "bags", "bag_target_kg", "total_actual_kg", "remarks"]


def prod_query(params: dict):
    stmt = select(ProductionRecord)
    if params.get("line"):
        stmt = stmt.where(ProductionRecord.product_line == params["line"])
    if params.get("status"):
        if params["status"] == "lot":
            stmt = stmt.where(ProductionRecord.lot_issue.is_(True))
        else:
            stmt = stmt.where(ProductionRecord.status == params["status"])
    if params.get("q"):
        like = f"%{params['q'].strip().lower()}%"
        lot_match = select(ProductionComponent.record_id).where(func.lower(ProductionComponent.lot_no).like(like))
        stmt = stmt.where(or_(
            func.lower(ProductionRecord.record_no).like(like), func.lower(ProductionRecord.shift).like(like),
            func.lower(ProductionRecord.recipe_name).like(like), ProductionRecord.id.in_(lot_match)))
    for key in ("from", "to"):
        if params.get(key):
            try:
                d = date.fromisoformat(params[key])
                stmt = stmt.where(ProductionRecord.prod_date >= d if key == "from" else ProductionRecord.prod_date <= d)
            except ValueError:
                pass
    return stmt


@router.get("")
def prod_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    params = dict(request.query_params)
    try:
        page = max(1, int(params.get("page", 1)))
    except ValueError:
        page = 1
    stmt = prod_query(params)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    records = db.scalars(
        stmt.options(selectinload(ProductionRecord.components), selectinload(ProductionRecord.created_by))
        .order_by(ProductionRecord.prod_date.desc(), ProductionRecord.id.desc())
        .offset((page - 1) * config.PAGE_SIZE).limit(config.PAGE_SIZE)
    ).all()
    lines = sorted(set(services.get_settings(db).product_line_list) |
                   set(db.scalars(select(ProductionRecord.product_line).distinct()).all()))
    return render(request, db, user, "prod_list.html", records=records, lines=lines, f=params,
                  page=page, pages=max(1, -(-total // config.PAGE_SIZE)), total=total)


def _form_context(db: Session) -> dict:
    materials = db.scalars(select(Material).where(Material.active.is_(True)).order_by(Material.name)).all()
    recipes = db.scalars(select(Recipe).where(Recipe.active.is_(True)).options(selectinload(Recipe.components))
                         .order_by(Recipe.name)).all()
    payload = {
        "materials": [{"id": m.id, "name": m.name} for m in materials],
        "lots": services.known_lots(db),
        "recipes": {r.id: {"line": r.product_line, "components": [
            {"material_id": c.material_id, "planned": c.quantity, "unit": c.unit} for c in r.components]}
            for r in recipes},
        "tolerance": services.get_settings(db).tolerance_pct,
    }
    return {"materials": materials, "recipes": recipes, "payload": payload}


@router.get("/new")
def prod_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("production.write"))):
    ctx = _form_context(db)
    if not ctx["materials"]:
        flash(request, "Add materials in Setup before logging production.", "warn")
        return redirect("/setup")
    return render(request, db, user, "prod_form.html", form={}, comps=[], **ctx)


@router.post("/new")
async def prod_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("production.write"))):
    raw = await request.form()
    form = {k: raw.get(k, "") for k in ("prod_date", "shift", "record_no", "product_line", "recipe_id", "bags",
                                         "bag_target_kg", "total_actual_kg", "remarks")}
    form["components"] = indexed_rows(raw, "c", ["material_id", "lot_no", "planned", "actual", "unit"])
    try:
        record = services.save_production(db, user, form)
    except services.ValidationError as e:
        return render(request, db, user, "prod_form.html", status_code=400, form=form,
                      comps=form["components"], errors=e.messages, **_form_context(db))
    flash(request, f"Production record {record.record_no} saved.")
    return redirect(f"/production/{record.id}")


@router.get("/import")
def import_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require("production.write"))):
    return render(request, db, user, "prod_import.html", columns=CSV_COLUMNS)


@router.get("/import/template.csv")
def import_template(user: User = Depends(require("production.write"))):
    return Response(",".join(CSV_COLUMNS) + "\r\n", media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="production-import-template.csv"'})


def parse_import(text: str) -> tuple[list[dict], list[str]]:
    """Group CSV rows into records by record_no (or by date+shift+line when record_no is empty)."""
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in ("date", "product_line", "material", "actual") if c not in headers]
    if missing:
        return [], [f"The file is missing the column(s): {', '.join(missing)}."]
    records: dict[str, dict] = {}
    for line_no, row in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if not any(row.values()):
            continue
        key = row.get("record_no") or f"{row.get('date')}|{row.get('shift')}|{row.get('product_line')}"
        rec = records.setdefault(key, {
            "prod_date": row.get("date"), "shift": row.get("shift", ""), "record_no": row.get("record_no", ""),
            "product_line": row.get("product_line"), "bags": row.get("bags", ""),
            "bag_target_kg": row.get("bag_target_kg", ""), "total_actual_kg": row.get("total_actual_kg", ""),
            "remarks": row.get("remarks", ""), "components": [], "_line": line_no})
        rec["components"].append({"material_name": row.get("material"), "lot_no": row.get("lot_no", ""),
                                  "planned": row.get("planned", ""), "actual": row.get("actual", ""),
                                  "unit": row.get("unit") or "kg"})
    return list(records.values()), []


@router.post("/import")
async def import_csv(request: Request, db: Session = Depends(get_db), user: User = Depends(require("production.write"))):
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return render(request, db, user, "prod_import.html", status_code=400, columns=CSV_COLUMNS,
                      errors=["Choose a CSV file to import."])
    data = await upload.read()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return render(request, db, user, "prod_import.html", status_code=400, columns=CSV_COLUMNS,
                      errors=["The file must be saved as CSV (UTF-8)."])
    records, errors = parse_import(text)
    results = []
    for rec in records:
        line = rec.pop("_line")
        try:
            saved = services.save_production(db, user, rec, source="csv")
            results.append({"line": line, "ok": True, "record_no": saved.record_no, "id": saved.id})
        except services.ValidationError as e:
            db.rollback()
            results.append({"line": line, "ok": False, "record_no": rec.get("record_no") or "—", "errors": e.messages})
    return render(request, db, user, "prod_import.html", columns=CSV_COLUMNS, errors=errors, results=results)


def _get(db: Session, record_id: int) -> ProductionRecord:
    rec = db.scalars(select(ProductionRecord).where(ProductionRecord.id == record_id)
                     .options(selectinload(ProductionRecord.components))).first()
    if not rec:
        raise HTTPException(404, "This production record does not exist.")
    return rec


@router.get("/{record_id}")
def prod_detail(record_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return render(request, db, user, "prod_detail.html", r=_get(db, record_id))


@router.post("/{record_id}/delete")
def prod_delete(record_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("records.delete"))):
    rec = _get(db, record_id)
    audit.record(db, user, "delete", "production", rec.record_no, {"line": rec.product_line, "date": rec.prod_date})
    db.delete(rec)
    db.commit()
    flash(request, f"Production record {rec.record_no} deleted.")
    return redirect("/production")
