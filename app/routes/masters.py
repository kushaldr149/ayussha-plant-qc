"""Customers, sites, vehicles and concrete grades (part of Setup)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import operations as ops
from ..db import get_db
from ..models import VEHICLE_TYPES, ConcreteGrade, Customer, Site, User, Vehicle
from ..security import check_csrf, require
from ..services import ValidationError
from ..web import flash, redirect, render

router = APIRouter(prefix="/setup", dependencies=[Depends(check_csrf)])


def _get(db: Session, model, oid: int):
    obj = db.get(model, oid)
    if not obj:
        raise HTTPException(404, "Not found.")
    return obj


@router.get("/masters")
def masters(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    customers = db.scalars(select(Customer).options(selectinload(Customer.sites)).order_by(Customer.name)).all()
    vehicles = db.scalars(select(Vehicle).order_by(Vehicle.vehicle_type, Vehicle.reg_no)).all()
    grades = db.scalars(select(ConcreteGrade).order_by(ConcreteGrade.name)).all()
    return render(request, db, user, "masters.html", customers=customers, vehicles=vehicles, grades=grades)


# ---------------------------------------------------------------- customers

@router.get("/customers/new")
def customer_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("masters.write"))):
    return render(request, db, user, "customer_form.html", c=None, form={})


@router.get("/customers/{cid}")
def customer_edit(cid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("masters.write"))):
    return render(request, db, user, "customer_form.html", c=_get(db, Customer, cid), form={})


@router.post("/customers/{cid}")
@router.post("/customers/new")
async def customer_save(request: Request, cid: int | None = None, db: Session = Depends(get_db),
                        user: User = Depends(require("masters.write"))):
    form = await request.form()
    c = _get(db, Customer, cid) if cid else None
    try:
        c = ops.save_customer(db, user, form, c)
    except ValidationError as e:
        return render(request, db, user, "customer_form.html", status_code=400, c=c, form=form, errors=e.messages)
    flash(request, f"Customer {c.name} saved.")
    return redirect("/setup/masters#customers")


# ---------------------------------------------------------------- sites

@router.get("/sites/new")
def site_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("masters.write"))):
    customers = db.scalars(select(Customer).order_by(Customer.name)).all()
    pre = request.query_params.get("customer", "")
    return render(request, db, user, "site_form.html", s=None, customers=customers, form={"customer_id": pre})


@router.get("/sites/{sid}")
def site_edit(sid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("masters.write"))):
    customers = db.scalars(select(Customer).order_by(Customer.name)).all()
    return render(request, db, user, "site_form.html", s=_get(db, Site, sid), customers=customers, form={})


@router.post("/sites/{sid}")
@router.post("/sites/new")
async def site_save(request: Request, sid: int | None = None, db: Session = Depends(get_db),
                    user: User = Depends(require("masters.write"))):
    form = await request.form()
    s = _get(db, Site, sid) if sid else None
    try:
        s = ops.save_site(db, user, form, s)
    except ValidationError as e:
        customers = db.scalars(select(Customer).order_by(Customer.name)).all()
        return render(request, db, user, "site_form.html", status_code=400, s=s, customers=customers, form=form,
                      errors=e.messages)
    flash(request, f"Site {s.name} saved.")
    return redirect("/setup/masters#customers")


# ---------------------------------------------------------------- vehicles

@router.get("/vehicles/new")
def vehicle_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("masters.write"))):
    return render(request, db, user, "vehicle_form.html", v=None, form={}, types=VEHICLE_TYPES)


@router.get("/vehicles/{vid}")
def vehicle_edit(vid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("masters.write"))):
    return render(request, db, user, "vehicle_form.html", v=_get(db, Vehicle, vid), form={}, types=VEHICLE_TYPES)


@router.post("/vehicles/{vid}")
@router.post("/vehicles/new")
async def vehicle_save(request: Request, vid: int | None = None, db: Session = Depends(get_db),
                       user: User = Depends(require("masters.write"))):
    form = await request.form()
    v = _get(db, Vehicle, vid) if vid else None
    try:
        v = ops.save_vehicle(db, user, form, v)
    except ValidationError as e:
        return render(request, db, user, "vehicle_form.html", status_code=400, v=v, form=form, types=VEHICLE_TYPES,
                      errors=e.messages)
    flash(request, f"Vehicle {v.reg_no} saved.")
    return redirect("/setup/masters#vehicles")


# ---------------------------------------------------------------- grades

@router.get("/grades/new")
def grade_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require("grades.write"))):
    return render(request, db, user, "grade_form.html", g=None, form={})


@router.get("/grades/{gid}")
def grade_edit(gid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("grades.write"))):
    return render(request, db, user, "grade_form.html", g=_get(db, ConcreteGrade, gid), form={})


@router.post("/grades/{gid}")
@router.post("/grades/new")
async def grade_save(request: Request, gid: int | None = None, db: Session = Depends(get_db),
                     user: User = Depends(require("grades.write"))):
    form = await request.form()
    g = _get(db, ConcreteGrade, gid) if gid else None
    try:
        g = ops.save_grade(db, user, form, g)
    except ValidationError as e:
        return render(request, db, user, "grade_form.html", status_code=400, g=g, form=form, errors=e.messages)
    flash(request, f"Grade {g.name} saved.")
    return redirect("/setup/masters#grades")
