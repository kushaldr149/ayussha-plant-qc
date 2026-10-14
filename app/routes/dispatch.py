"""Customer orders and dispatch to site."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import audit, config
from .. import operations as ops
from ..db import get_db
from ..models import (
    DELIVERY_STATUSES, ORDER_STATUSES, NCR, ConcreteGrade, CubeSample, Customer, Dispatch, DispatchItem, Order,
    ProductionRecord, Site, User, Vehicle,
)
from ..security import check_csrf, require
from ..services import ValidationError
from ..web import flash, indexed_rows, redirect, render

router = APIRouter(dependencies=[Depends(check_csrf)])


def _page(request: Request) -> int:
    try:
        return max(1, int(request.query_params.get("page", 1)))
    except ValueError:
        return 1


# ================================================================ orders

def _order_ctx(db: Session) -> dict:
    customers = db.scalars(select(Customer).where(Customer.active.is_(True)).options(selectinload(Customer.sites))
                           .order_by(Customer.name)).all()
    grades = db.scalars(select(ConcreteGrade).where(ConcreteGrade.active.is_(True)).order_by(ConcreteGrade.name)).all()
    sites = {c.id: [{"id": s.id, "name": s.name} for s in c.sites if s.active] for c in customers}
    from ..models import Recipe
    recipes = db.scalars(select(Recipe).where(Recipe.active.is_(True)).order_by(Recipe.name)).all()
    return {"customers": customers, "grades": grades, "sites_json": sites, "statuses": ORDER_STATUSES, "recipes": recipes}


@router.get("/orders")
def orders_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    f = dict(request.query_params)
    stmt = select(Order)
    if f.get("status"):
        stmt = stmt.where(Order.status == f["status"])
    if f.get("q"):
        like = f"%{f['q'].strip().lower()}%"
        stmt = stmt.join(Customer).where(or_(func.lower(Order.order_no).like(like), func.lower(Customer.name).like(like),
                                             func.lower(Order.customer_ref).like(like)))
    page = _page(request)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    orders = db.scalars(stmt.options(selectinload(Order.customer), selectinload(Order.site), selectinload(Order.grade),
                                     selectinload(Order.dispatches))
                        .order_by(Order.order_date.desc(), Order.id.desc())
                        .offset((page - 1) * config.PAGE_SIZE).limit(config.PAGE_SIZE)).all()
    return render(request, db, user, "orders.html", orders=orders, f=f, statuses=ORDER_STATUSES, page=page,
                  pages=max(1, -(-total // config.PAGE_SIZE)), total=total)


@router.get("/orders/new")
def order_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("orders.write"))):
    ctx = _order_ctx(db)
    if not ctx["customers"]:
        flash(request, "Add a customer in Setup → Customers, sites and vehicles first.", "warn")
        return redirect("/setup/masters")
    return render(request, db, user, "order_form.html", o=None, form={}, **ctx)


@router.post("/orders/new")
async def order_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("orders.write"))):
    form = await request.form()
    try:
        o = ops.save_order(db, user, form)
    except ValidationError as e:
        return render(request, db, user, "order_form.html", status_code=400, o=None, form=form, errors=e.messages,
                      **_order_ctx(db))
    flash(request, f"Order {o.order_no} saved.")
    return redirect(f"/orders/{o.id}")


def _order(db: Session, oid: int) -> Order:
    o = db.scalars(select(Order).where(Order.id == oid).options(
        selectinload(Order.dispatches).selectinload(Dispatch.items))).first()
    if not o:
        raise HTTPException(404, "This order does not exist.")
    return o


@router.get("/orders/{oid}")
def order_detail(oid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    o = _order(db, oid)
    delivered = sum(d.delivered_m3 or 0 for d in o.dispatches if d.status == "Delivered")
    return render(request, db, user, "order_detail.html", o=o, delivered_m3=delivered, form={}, **_order_ctx(db))


@router.post("/orders/{oid}")
async def order_update(oid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("orders.write"))):
    o = _order(db, oid)
    form = await request.form()
    try:
        ops.save_order(db, user, form, o)
    except ValidationError as e:
        delivered = sum(d.delivered_m3 or 0 for d in o.dispatches if d.status == "Delivered")
        return render(request, db, user, "order_detail.html", status_code=400, o=o, delivered_m3=delivered, form=form,
                      errors=e.messages, **_order_ctx(db))
    flash(request, f"Order {o.order_no} updated.")
    return redirect(f"/orders/{o.id}")


# ================================================================ dispatch

@router.get("/dispatch")
def dispatch_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    f = dict(request.query_params)
    stmt = select(Dispatch)
    if f.get("status"):
        stmt = stmt.where(Dispatch.status == f["status"])
    for key in ("from", "to"):
        if f.get(key):
            try:
                d = date.fromisoformat(f[key])
                stmt = stmt.where(Dispatch.dispatch_date >= d if key == "from" else Dispatch.dispatch_date <= d)
            except ValueError:
                pass
    if f.get("q"):
        like = f"%{f['q'].strip().lower()}%"
        stmt = stmt.join(Order).join(Customer).where(or_(
            func.lower(Dispatch.dispatch_no).like(like), func.lower(Order.order_no).like(like),
            func.lower(Customer.name).like(like), func.lower(Dispatch.driver_name).like(like)))
    page = _page(request)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.options(selectinload(Dispatch.order).selectinload(Order.customer),
                                   selectinload(Dispatch.order).selectinload(Order.site),
                                   selectinload(Dispatch.items), selectinload(Dispatch.truck), selectinload(Dispatch.mixer))
                      .order_by(Dispatch.dispatch_date.desc(), Dispatch.id.desc())
                      .offset((page - 1) * config.PAGE_SIZE).limit(config.PAGE_SIZE)).all()
    return render(request, db, user, "dispatch_list.html", rows=rows, f=f, statuses=DELIVERY_STATUSES, page=page,
                  pages=max(1, -(-total // config.PAGE_SIZE)), total=total)


def _dispatch_ctx(db: Session) -> dict:
    orders = db.scalars(select(Order).where(Order.status == "Open").options(
        selectinload(Order.customer), selectinload(Order.site), selectinload(Order.grade))
        .order_by(Order.order_date.desc())).all()
    vehicles = db.scalars(select(Vehicle).where(Vehicle.active.is_(True)).order_by(Vehicle.reg_no)).all()
    stock = ops.finished_stock(db)
    payload = [{"id": s["record"].id, "label": f"{s['record'].record_no} · {s['record'].product_line} · "
                f"{s['record'].prod_date:%d %b %Y}", "line": s["record"].product_line, "available": s["available"],
                "flagged": s["flagged"]} for s in stock]
    from ..models import Pack
    packs = db.scalars(select(Pack).where(Pack.status == "Packed", Pack.order_id.in_([o.id for o in orders]))
                       .options(selectinload(Pack.items)).order_by(Pack.order_id, Pack.kind, Pack.pack_no)).all()
    return {"packs": packs, "orders": orders, "trucks": [v for v in vehicles if v.vehicle_type != "Mixer on wheels"],
            "mixers": [v for v in vehicles if v.vehicle_type == "Mixer on wheels"], "stock_json": payload}


@router.get("/dispatch/new")
def dispatch_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("dispatch.write"))):
    ctx = _dispatch_ctx(db)
    if not ctx["orders"]:
        flash(request, "Create an open customer order before dispatching.", "warn")
        return redirect("/orders")
    pre = {"order_id": request.query_params.get("order", "")}
    return render(request, db, user, "dispatch_form.html", form=pre, items=[], **ctx)


@router.post("/dispatch/new")
async def dispatch_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("dispatch.write"))):
    raw = await request.form()
    form = {k: raw.get(k, "") for k in ("dispatch_date", "order_id", "truck_id", "mixer_id", "driver_name",
                                         "driver_phone", "planned_m3", "remarks", "departed_at")}
    form["items"] = indexed_rows(raw, "i", ["production_id", "bags"])
    form["pack_ids"] = raw.getlist("pack_ids")
    try:
        d = ops.save_dispatch(db, user, form)
    except ValidationError as e:
        return render(request, db, user, "dispatch_form.html", status_code=400, form=form, items=form["items"],
                      errors=e.messages, **_dispatch_ctx(db))
    flash(request, f"Dispatch {d.dispatch_no} saved.")
    return redirect(f"/dispatch/{d.id}")


def _dispatch(db: Session, did: int) -> Dispatch:
    d = db.scalars(select(Dispatch).where(Dispatch.id == did).options(
        selectinload(Dispatch.items).selectinload(DispatchItem.production).selectinload(ProductionRecord.components),
        selectinload(Dispatch.order))).first()
    if not d:
        raise HTTPException(404, "This dispatch does not exist.")
    return d


def _pack_ctx(db: Session, d: Dispatch) -> dict:
    from ..models import Pack, SiteMix
    packs = db.scalars(select(Pack).where(Pack.dispatch_id == d.id).options(selectinload(Pack.items))
                       .order_by(Pack.kind, Pack.pack_no)).all()
    mixes = db.scalars(select(SiteMix).where(SiteMix.dispatch_id == d.id).order_by(SiteMix.mix_date)).all()
    return {"packs": packs, "mixes": mixes}


@router.get("/dispatch/{did}")
def dispatch_detail(did: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    d = _dispatch(db, did)
    samples = db.scalars(select(CubeSample).where(CubeSample.dispatch_id == d.id)).all()
    ncrs = db.scalars(select(NCR).where(NCR.dispatch_id == d.id)).all()
    return render(request, db, user, "dispatch_detail.html", d=d, samples=samples, ncrs=ncrs,
                  statuses=DELIVERY_STATUSES, form={}, **_pack_ctx(db, d))


@router.post("/dispatch/{did}/delivery")
async def dispatch_delivery(did: int, request: Request, db: Session = Depends(get_db),
                            user: User = Depends(require("dispatch.write"))):
    d = _dispatch(db, did)
    form = await request.form()
    try:
        ops.update_delivery(db, user, d, form)
    except ValidationError as e:
        samples = db.scalars(select(CubeSample).where(CubeSample.dispatch_id == d.id)).all()
        ncrs = db.scalars(select(NCR).where(NCR.dispatch_id == d.id)).all()
        return render(request, db, user, "dispatch_detail.html", status_code=400, d=d, samples=samples, ncrs=ncrs, **_pack_ctx(db, d),
                      statuses=DELIVERY_STATUSES, form=form, errors=e.messages)
    flash(request, f"Dispatch {d.dispatch_no} updated.")
    return redirect(f"/dispatch/{d.id}")


@router.post("/dispatch/{did}/delete")
def dispatch_delete(did: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("records.delete"))):
    d = _dispatch(db, did)
    if db.scalar(select(func.count(CubeSample.id)).where(CubeSample.dispatch_id == d.id)) or \
       db.scalar(select(func.count(NCR.id)).where(NCR.dispatch_id == d.id)):
        flash(request, "Strength samples or NCRs refer to this dispatch. Set its status to Cancelled instead.", "error")
        return redirect(f"/dispatch/{d.id}")
    audit.record(db, user, "delete", "dispatch", d.dispatch_no, {"order": d.order.order_no})
    db.delete(d)
    db.commit()
    flash(request, f"Dispatch {d.dispatch_no} deleted.")
    return redirect("/dispatch")
