"""Setup (administrators): plant settings, materials, test parameters, recipes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import audit, logic, services
from .. import is_library as lib
from ..db import get_db
from ..models import (
    CATEGORIES, UNITS, Material, ProductionComponent, QCParameter, QCResult, QCTest, Recipe, RecipeComponent, StockAdjustment, User,
)
from ..security import check_csrf, require
from ..web import flash, indexed_rows, redirect, render

router = APIRouter(prefix="/setup", dependencies=[Depends(check_csrf)])


@router.get("")
def setup_home(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    materials = db.scalars(select(Material).options(selectinload(Material.parameters)).order_by(Material.name)).all()
    recipes = db.scalars(select(Recipe).options(selectinload(Recipe.components).selectinload(RecipeComponent.material))
                         .order_by(Recipe.name)).all()
    return render(request, db, user, "setup.html", materials=materials, recipes=recipes)


# ---------------------------------------------------------------- settings

@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require("setup.write"))):
    return render(request, db, user, "settings_form.html", form=None)


@router.post("/settings")
async def settings_save(request: Request, db: Session = Depends(get_db), user: User = Depends(require("setup.write"))):
    form = await request.form()
    errors: list[str] = []
    tol = services.parse_num(form.get("tolerance_pct"), "Batching tolerance", errors)
    if tol is not None and tol < 0:
        errors.append("Batching tolerance must be zero or more.")
    if errors:
        return render(request, db, user, "settings_form.html", status_code=400, errors=errors, form=form)
    s = services.get_settings(db)
    before = {k: getattr(s, k) for k in ("company_name", "plant_name", "plant_address", "tolerance_pct", "product_lines", "shifts")}
    s.company_name = str(form.get("company_name", "")).strip()
    s.plant_name = str(form.get("plant_name", "")).strip()
    s.plant_address = str(form.get("plant_address", "")).strip()
    s.tolerance_pct = tol
    clean = lambda v: "\n".join(x.strip() for x in str(v or "").splitlines() if x.strip())  # noqa: E731
    s.product_lines = clean(form.get("product_lines"))
    s.shifts = clean(form.get("shifts"))
    audit.record(db, user, "update", "settings", "plant", {"before": before})
    db.commit()
    flash(request, "Plant settings saved.")
    return redirect("/setup")


# ---------------------------------------------------------------- materials

@router.get("/materials/new")
def material_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("setup.write"))):
    return render(request, db, user, "material_form.html", m=None, form={})


@router.get("/materials/{mid}")
def material_edit(mid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("setup.write"))):
    m = db.get(Material, mid) or _404()
    return render(request, db, user, "material_form.html", m=m, form={})


def _404():
    raise HTTPException(404, "Not found.")


@router.post("/materials/{mid}")
@router.post("/materials/new")
async def material_save(request: Request, mid: int | None = None, db: Session = Depends(get_db),
                        user: User = Depends(require("setup.write"))):
    form = await request.form()
    m = db.get(Material, mid) if mid else None
    if mid and not m:
        _404()
    name = str(form.get("name", "")).strip()
    category = str(form.get("category", ""))
    errors = []
    if not name:
        errors.append("Enter the material name.")
    if category not in CATEGORIES:
        errors.append("Select a category.")
    stock_unit = str(form.get("stock_unit") or "kg")
    if stock_unit not in UNITS:
        errors.append("Select a stock unit.")
    reorder = services.parse_num(form.get("reorder_level"), "Reorder level", errors)
    dup = db.scalars(select(Material).where(func.lower(Material.name) == name.lower())).first()
    if dup and (not m or dup.id != m.id):
        errors.append("A material with this name already exists.")
    if errors:
        return render(request, db, user, "material_form.html", status_code=400, m=m, form=form, errors=errors)
    is_new = m is None
    if is_new:
        m = Material(name=name, category=category)
        db.add(m)
    m.name, m.category = name, category
    m.supplier = str(form.get("supplier", "")).strip()
    m.notes = str(form.get("notes", "")).strip()
    m.stock_unit, m.reorder_level = stock_unit, reorder
    m.active = form.get("active") == "on" if not is_new else True
    db.flush()
    audit.record(db, user, "create" if is_new else "update", "material", m.id, {"name": name, "category": category})
    db.commit()
    flash(request, f"Material {name} saved.")
    return redirect("/setup#materials")


@router.post("/materials/{mid}/delete")
def material_delete(mid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("setup.write"))):
    m = db.get(Material, mid) or _404()
    used = (db.scalar(select(func.count(QCTest.id)).where(QCTest.material_id == mid)) or 0) + \
           (db.scalar(select(func.count(ProductionComponent.id)).where(ProductionComponent.material_id == mid)) or 0) + \
           (db.scalar(select(func.count(RecipeComponent.id)).where(RecipeComponent.material_id == mid)) or 0) + \
           (db.scalar(select(func.count(StockAdjustment.id)).where(StockAdjustment.material_id == mid)) or 0)
    if used:
        flash(request, "This material is used in tests, production records or recipes. Mark it inactive instead of deleting it.", "error")
        return redirect(f"/setup/materials/{mid}")
    for p in list(m.parameters):
        db.delete(p)
    audit.record(db, user, "delete", "material", mid, {"name": m.name})
    db.delete(m)
    db.commit()
    flash(request, f"Material {m.name} deleted.")
    return redirect("/setup#materials")


# ---------------------------------------------------------------- test parameters

def _materials(db: Session):
    return db.scalars(select(Material).order_by(Material.name)).all()


def _param_ctx() -> dict:
    from .. import is_library as _lib
    return {"frequencies": _lib.FREQUENCIES, "groups": _lib.GROUPS,
            "calcs": [("", "None")] + [(k, c.title) for k, c in _lib.CALCS.items()] + [("sieve", "Sieve analysis")]}


@router.get("/parameters/new")
def param_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("setup.write"))):
    pre = request.query_params.get("material")
    return render(request, db, user, "param_form.html", p=None, materials=_materials(db),
                  form={"material_id": pre} if pre else {}, **_param_ctx())


@router.get("/parameters/{pid}")
def param_edit(pid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("setup.write"))):
    p = db.get(QCParameter, pid) or _404()
    return render(request, db, user, "param_form.html", p=p, materials=_materials(db), form={}, **_param_ctx())


@router.post("/parameters/{pid}")
@router.post("/parameters/new")
async def param_save(request: Request, pid: int | None = None, db: Session = Depends(get_db),
                     user: User = Depends(require("setup.write"))):
    form = await request.form()
    p = db.get(QCParameter, pid) if pid else None
    if pid and not p:
        _404()
    errors: list[str] = []
    try:
        material = db.get(Material, int(form.get("material_id") or 0))
    except ValueError:
        material = None
    if not material:
        errors.append("Select the material.")
    name = str(form.get("name", "")).strip()
    if not name:
        errors.append("Enter the parameter name.")
    mn = services.parse_num(form.get("min_value"), "Minimum", errors)
    mx = services.parse_num(form.get("max_value"), "Maximum", errors)
    if mn is not None and mx is not None and mn > mx:
        errors.append("Minimum is greater than maximum.")
    try:
        order = int(form.get("sort_order") or 0)
    except ValueError:
        order = 0
    if material and name:
        dup = db.scalars(select(QCParameter).where(QCParameter.material_id == material.id,
                                                   func.lower(QCParameter.name) == name.lower())).first()
        if dup and (not p or dup.id != p.id):
            errors.append("This material already has a parameter with this name.")
    if errors:
        return render(request, db, user, "param_form.html", status_code=400, p=p, materials=_materials(db),
                      form=form, errors=errors, **_param_ctx())
    is_new = p is None
    before = None if is_new else {"min": p.min_value, "max": p.max_value, "unit": p.unit, "method": p.method}
    if is_new:
        p = QCParameter(material_id=material.id, name=name)
        db.add(p)
    p.material_id, p.name = material.id, name
    p.unit = str(form.get("unit", "")).strip()
    p.min_value, p.max_value = mn, mx
    p.method = str(form.get("method", "")).strip()
    p.sort_order = order
    p.group_name = str(form.get("group_name", "")).strip()
    freq = str(form.get("frequency") or "Every lot")
    p.frequency = freq if freq in lib.FREQUENCIES else "Every lot"
    p.value_type = "passfail" if form.get("value_type") == "passfail" else "number"
    calc = str(form.get("calc") or "")
    p.calc = calc if calc in lib.CALCS or calc == "sieve" else ""
    p.sieve_mm = services.parse_num(form.get("sieve_mm"), "Sieve size", []) if p.calc == "sieve" else None
    p.note = str(form.get("note", "")).strip()
    p.active = True if is_new else form.get("active") == "on"
    db.flush()
    audit.record(db, user, "create" if is_new else "update", "parameter", p.id, {
        "material": material.name, "name": name, "limit": logic.limit_text(mn, mx, p.unit), "before": before})
    db.commit()
    flash(request, f"Parameter {name} saved for {material.name}.")
    return redirect("/setup#parameters")


@router.post("/parameters/{pid}/delete")
def param_delete(pid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("setup.write"))):
    p = db.get(QCParameter, pid) or _404()
    if db.scalar(select(func.count(QCResult.id)).where(QCResult.parameter_id == pid)):
        flash(request, "Tests have been recorded against this parameter. Mark it inactive instead of deleting it.", "error")
        return redirect(f"/setup/parameters/{pid}")
    audit.record(db, user, "delete", "parameter", pid, {"name": p.name})
    db.delete(p)
    db.commit()
    flash(request, f"Parameter {p.name} deleted.")
    return redirect("/setup#parameters")


# ---------------------------------------------------------------- recipes

@router.get("/recipes/new")
def recipe_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("setup.write"))):
    return render(request, db, user, "recipe_form.html", r=None, materials=_materials(db), form={}, comps=[{}])


@router.get("/recipes/{rid}")
def recipe_edit(rid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("setup.write"))):
    r = db.get(Recipe, rid) or _404()
    comps = [{"material_id": c.material_id, "quantity": c.quantity, "unit": c.unit} for c in r.components] or [{}]
    return render(request, db, user, "recipe_form.html", r=r, materials=_materials(db), form={}, comps=comps)


@router.post("/recipes/{rid}")
@router.post("/recipes/new")
async def recipe_save(request: Request, rid: int | None = None, db: Session = Depends(get_db),
                      user: User = Depends(require("setup.write"))):
    form = await request.form()
    r = db.get(Recipe, rid) if rid else None
    if rid and not r:
        _404()
    errors: list[str] = []
    name = str(form.get("name", "")).strip()
    if not name:
        errors.append("Enter the recipe name.")
    dup = db.scalars(select(Recipe).where(func.lower(Recipe.name) == name.lower())).first() if name else None
    if dup and (not r or dup.id != r.id):
        errors.append("A recipe with this name already exists.")
    rows = indexed_rows(form, "c", ["material_id", "quantity", "unit"])
    comps = []
    for i, row in enumerate(rows, start=1):
        if not row.get("material_id"):
            continue
        qty = services.parse_num(row.get("quantity"), f"Component {i} quantity", errors)
        if qty is None:
            errors.append(f"Component {i}: enter the planned quantity.")
            continue
        comps.append(RecipeComponent(material_id=int(row["material_id"]), quantity=qty, unit=row.get("unit") or "kg"))
    if not comps and not errors:
        errors.append("Add at least one component.")
    if errors:
        return render(request, db, user, "recipe_form.html", status_code=400, r=r, materials=_materials(db),
                      form=form, comps=rows or [{}], errors=errors)
    is_new = r is None
    if is_new:
        r = Recipe(name=name)
        db.add(r)
    r.name = name
    r.product_line = str(form.get("product_line", "")).strip()
    r.notes = str(form.get("notes", "")).strip()
    r.active = True if is_new else form.get("active") == "on"
    r.components.clear()
    db.flush()
    r.components.extend(comps)
    db.flush()
    audit.record(db, user, "create" if is_new else "update", "recipe", r.id, {
        "name": name, "components": [(c.material_id, c.quantity, c.unit) for c in comps]})
    db.commit()
    flash(request, f"Recipe {name} saved.")
    return redirect("/setup#recipes")


@router.post("/recipes/{rid}/delete")
def recipe_delete(rid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("setup.write"))):
    from ..models import ProductionRecord
    r = db.get(Recipe, rid) or _404()
    if db.scalar(select(func.count(ProductionRecord.id)).where(ProductionRecord.recipe_id == rid)):
        flash(request, "Production records use this recipe. Mark it inactive instead of deleting it.", "error")
        return redirect(f"/setup/recipes/{rid}")
    audit.record(db, user, "delete", "recipe", rid, {"name": r.name})
    db.delete(r)
    db.commit()
    flash(request, f"Recipe {r.name} deleted.")
    return redirect("/setup#recipes")


# ---------------------------------------------------------------- IS 383 test sets

from .. import is_library as lib  # noqa: E402


def _template_options(material: Material) -> dict:
    fine = material.category == "Fine aggregate"
    return {"fine": fine, "coarse_sources": lib.COARSE_SOURCES, "fine_sources": lib.FINE_SOURCES,
            "gradings": list(lib.COARSE_GRADING), "zones": list(lib.FINE_ZONES), "uses": lib.USES,
            "sources_list": lib.SOURCES}


def _build_set(material: Material, opts) -> list:
    if material.category == "Fine aggregate":
        return lib.fine_set(str(opts.get("source", "")), str(opts.get("zone", "")), opts.get("frost") == "on")
    if material.category == "Coarse aggregate":
        return lib.coarse_set(str(opts.get("source", "")), str(opts.get("grading", "")), str(opts.get("use", "")),
                              opts.get("m65") == "on", opts.get("frost") == "on")
    raise ValueError("IS 383 test sets are available for materials in the Coarse aggregate or Fine aggregate category.")


@router.get("/materials/{mid}/is383")
def is383_page(mid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("setup.write"))):
    m = db.get(Material, mid) or _404()
    if m.category not in ("Coarse aggregate", "Fine aggregate"):
        flash(request, "IS 383 test sets are for materials in the Coarse aggregate or Fine aggregate category. "
                       "Change the material's category first.", "warn")
        return redirect(f"/setup/materials/{mid}")
    q = request.query_params
    preview, error = None, None
    if q.get("preview"):
        try:
            preview = _build_set(m, q)
        except ValueError as e:
            error = str(e)
    existing = {p.name.lower() for p in m.parameters}
    return render(request, db, user, "is383_form.html", m=m, o=_template_options(m), q=q, preview=preview,
                  existing=existing, errors=[error] if error else None)


@router.post("/materials/{mid}/is383")
async def is383_apply(mid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("setup.write"))):
    m = db.get(Material, mid) or _404()
    form = await request.form()
    try:
        items = _build_set(m, form)
    except ValueError as e:
        flash(request, str(e), "error")
        return redirect(f"/setup/materials/{mid}/is383")
    by_name = {p.name.lower(): p for p in m.parameters}
    added = updated = 0
    for order, it in enumerate(items, start=1):
        p = by_name.get(it.name.lower())
        if p is None:
            p = QCParameter(material_id=m.id, name=it.name)
            db.add(p)
            added += 1
        else:
            updated += 1
        p.unit, p.min_value, p.max_value = it.unit, it.min, it.max
        p.method, p.group_name, p.frequency = it.method_text, it.group, it.frequency
        p.calc, p.value_type, p.sieve_mm, p.note = it.calc, it.value_type, it.sieve_mm, it.note
        p.sort_order, p.active = order, True
    keep = {it.name.lower() for it in items}
    deactivated = 0
    if form.get("deactivate_others") == "on":
        for p in m.parameters:
            if p.name.lower() not in keep and p.active:
                p.active = False
                deactivated += 1
    db.flush()
    audit.record(db, user, "apply_is383", "material", m.id, {
        "material": m.name, "options": {k: str(form.get(k, "")) for k in ("source", "grading", "zone", "use", "m65", "frost")},
        "added": added, "updated": updated, "deactivated": deactivated})
    db.commit()
    msg = f"IS 383 test set applied to {m.name}: {added} parameter(s) added, {updated} updated"
    flash(request, msg + (f", {deactivated} other parameter(s) marked inactive." if deactivated else "."))
    return redirect(f"/setup/materials/{mid}")
