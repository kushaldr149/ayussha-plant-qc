"""Raw material stock by lot, finished bag stock, and stock adjustments."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import operations as ops
from ..db import get_db
from ..models import UNITS, Material, StockAdjustment, User
from ..security import check_csrf, require
from ..services import ValidationError
from ..web import flash, redirect, render

router = APIRouter(prefix="/stock", dependencies=[Depends(check_csrf)])


@router.get("")
def stock_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    raw = ops.raw_stock(db)
    finished = ops.finished_stock(db)
    by_line: dict[str, int] = {}
    for f in finished:
        by_line[f["record"].product_line] = by_line.get(f["record"].product_line, 0) + f["available"]
    return render(request, db, user, "stock.html", raw=raw, finished=finished, by_line=by_line)


@router.get("/material/{mid}")
def material_stock(mid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    ms = next((m for m in ops.raw_stock(db) if m.material.id == mid), None)
    if not ms:
        raise HTTPException(404, "This material does not exist.")
    adjustments = db.scalars(select(StockAdjustment).where(StockAdjustment.material_id == mid)
                             .order_by(StockAdjustment.adj_date.desc(), StockAdjustment.id.desc())).all()
    from datetime import date as _date
    lots = sorted(ms.lots.values(), key=lambda lb: lb.last_date or _date.min, reverse=True)
    return render(request, db, user, "stock_material.html", ms=ms, lots=lots, adjustments=adjustments)


def _ctx(db: Session) -> dict:
    return {"materials": db.scalars(select(Material).order_by(Material.name)).all(), "units": UNITS}


@router.get("/adjust")
def adjust_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require("stock.adjust"))):
    pre = {"material_id": request.query_params.get("material", ""), "lot_no": request.query_params.get("lot", "")}
    return render(request, db, user, "stock_adjust.html", form=pre, **_ctx(db))


@router.post("/adjust")
async def adjust_save(request: Request, db: Session = Depends(get_db), user: User = Depends(require("stock.adjust"))):
    form = await request.form()
    try:
        adj = ops.save_adjustment(db, user, form)
    except ValidationError as e:
        return render(request, db, user, "stock_adjust.html", status_code=400, form=form, errors=e.messages, **_ctx(db))
    flash(request, "Stock adjustment saved.")
    return redirect(f"/stock/material/{adj.material_id}")
