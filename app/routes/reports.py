"""Reports page, PDF documents, Excel exports and AI review."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import ai, audit, config, logic, reports, services
from ..db import get_db
from ..models import AIReview, ProductionRecord, QCTest, User
from ..security import check_csrf, require
from ..web import flash, parse_period, redirect, render
from .production import prod_query
from .qc import qc_query

router = APIRouter(dependencies=[Depends(check_csrf)])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _file(data: bytes, media: str, filename: str, inline: bool = False) -> Response:
    disp = "inline" if inline else "attachment"
    return Response(data, media_type=media, headers={"Content-Disposition": f'{disp}; filename="{filename}"'})


@router.get("/reports")
def reports_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require("reports"))):
    start, end = parse_period(request.query_params.get("from"), request.query_params.get("to"))
    return render(request, db, user, "reports.html", start=start, end=end)


@router.get("/reports/qc.xlsx")
def qc_xlsx(request: Request, db: Session = Depends(get_db), user: User = Depends(require("reports"))):
    params = dict(request.query_params)
    tests = db.scalars(qc_query(params).options(selectinload(QCTest.results), selectinload(QCTest.created_by))
                       .order_by(QCTest.test_date, QCTest.id).limit(20000)).all()
    name = f"material-qc-{params.get('from') or 'all'}-to-{params.get('to') or config.local_today().isoformat()}.xlsx"
    return _file(reports.qc_excel(tests), XLSX, name)


@router.get("/reports/production.xlsx")
def prod_xlsx(request: Request, db: Session = Depends(get_db), user: User = Depends(require("reports"))):
    params = dict(request.query_params)
    records = db.scalars(prod_query(params).options(selectinload(ProductionRecord.components),
                                                     selectinload(ProductionRecord.created_by))
                         .order_by(ProductionRecord.prod_date, ProductionRecord.id).limit(20000)).all()
    name = f"production-log-{params.get('from') or 'all'}-to-{params.get('to') or config.local_today().isoformat()}.xlsx"
    return _file(reports.production_excel(records), XLSX, name)


@router.get("/qc/{test_id}/report.pdf")
def qc_pdf(test_id: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    test = db.scalars(select(QCTest).where(QCTest.id == test_id).options(selectinload(QCTest.results))).first()
    if not test:
        raise HTTPException(404, "This test does not exist.")
    return _file(reports.qc_report_pdf(test, services.get_settings(db)), "application/pdf",
                 f"{test.test_no}.pdf", inline=True)


@router.get("/production/{record_id}/certificate.pdf")
def prod_pdf(record_id: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    rec = db.scalars(select(ProductionRecord).where(ProductionRecord.id == record_id)
                     .options(selectinload(ProductionRecord.components))).first()
    if not rec:
        raise HTTPException(404, "This production record does not exist.")
    ids = [c.lot_test_id for c in rec.components if c.lot_test_id]
    tests = {t.id: t for t in db.scalars(select(QCTest).where(QCTest.id.in_(ids))).all()} if ids else {}
    return _file(reports.batch_certificate_pdf(rec, services.get_settings(db), tests), "application/pdf",
                 f"{rec.record_no}-certificate.pdf", inline=True)


# ---------------------------------------------------------------- AI review

@router.get("/ai")
def ai_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require("ai.review"))):
    start, end = parse_period(request.query_params.get("from"), request.query_params.get("to"))
    past = db.scalars(select(AIReview).order_by(AIReview.id.desc()).limit(30)).all()
    return render(request, db, user, "ai.html", start=start, end=end, past=past, enabled=ai.enabled(),
                  model=config.CLAUDE_MODEL)


@router.post("/ai/run")
async def ai_run(request: Request, db: Session = Depends(get_db), user: User = Depends(require("ai.review"))):
    form = await request.form()
    start, end = parse_period(form.get("from"), form.get("to"))
    data = services.review_data(db, start, end, config.AI_MAX_RECORDS)
    from .. import operations as _ops
    data.update(_ops.review_extra(db, start, end, config.AI_MAX_RECORDS))
    from .. import process as _proc
    data.update(_proc.review_data(db, start, end, config.AI_MAX_RECORDS))
    from .. import sensors as _sn
    data.update(_sn.review_data(db, start, end, config.AI_MAX_RECORDS))
    qn, pn = len(data["material_tests"]), len(data["production_records"])
    if not any(data.get(k) for k in ("material_tests", "production_records", "dispatches", "strength_samples", "ncrs",
                                     "coating_batches", "grinding_batches", "bags", "site_mixes",
                                     "sensor_readings_outside_limits")):
        flash(request, "There are no records in this period to review.", "warn")
        return redirect(f"/ai?from={start}&to={end}")
    try:
        text = await run_in_threadpool(ai.review, data)
    except ai.AIUnavailable as e:
        flash(request, str(e), "error")
        return redirect(f"/ai?from={start}&to={end}")
    rev = AIReview(created_by_id=user.id, period_from=start, period_to=end, model=config.CLAUDE_MODEL,
                   qc_count=qn, production_count=pn, summary=text)
    db.add(rev)
    db.flush()
    audit.record(db, user, "create", "ai_review", rev.id, {"from": start, "to": end, "tests": qn, "production": pn})
    db.commit()
    return redirect(f"/ai/{rev.id}")


@router.get("/ai/{review_id}")
def ai_detail(review_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("ai.review"))):
    rev = db.get(AIReview, review_id)
    if not rev:
        raise HTTPException(404, "This review does not exist.")
    return render(request, db, user, "ai_detail.html", rev=rev, limit=config.AI_MAX_RECORDS)


# ================================================================ dispatch, strength, stock, NCR, equipment

from datetime import date as _date  # noqa: E402

from .. import operations as ops  # noqa: E402
from ..models import (  # noqa: E402
    NCR, ConcreteGrade, CubeSample, Dispatch, DispatchItem, Equipment, Order,
)


def _date_filter(stmt, column, params: dict):
    for key in ("from", "to"):
        if params.get(key):
            try:
                d = _date.fromisoformat(params[key])
                stmt = stmt.where(column >= d if key == "from" else column <= d)
            except ValueError:
                pass
    return stmt


def _stamp(params: dict) -> str:
    return f"{params.get('from') or 'all'}-to-{params.get('to') or config.local_today().isoformat()}"


@router.get("/dispatch/{did}/note.pdf")
def delivery_note(did: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    d = db.scalars(select(Dispatch).where(Dispatch.id == did).options(
        selectinload(Dispatch.items).selectinload(DispatchItem.production))).first()
    if not d:
        raise HTTPException(404, "This dispatch does not exist.")
    from ..models import Pack
    packs = db.scalars(select(Pack).where(Pack.dispatch_id == d.id).options(selectinload(Pack.items))
                       .order_by(Pack.kind, Pack.pack_no)).all()
    return _file(reports.delivery_note_pdf(d, services.get_settings(db), packs), "application/pdf", f"{d.dispatch_no}.pdf",
                 inline=True)


@router.get("/strength/{sid}/report.pdf")
def strength_pdf(sid: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    s = db.scalars(select(CubeSample).where(CubeSample.id == sid).options(selectinload(CubeSample.results))).first()
    if not s:
        raise HTTPException(404, "This sample does not exist.")
    return _file(reports.strength_report_pdf(s, ops.sample_summary(s), services.get_settings(db)), "application/pdf",
                 f"{s.sample_no}.pdf", inline=True)


@router.get("/reports/dispatch.xlsx")
def dispatch_xlsx(request: Request, db: Session = Depends(get_db), user: User = Depends(require("reports"))):
    params = dict(request.query_params)
    stmt = _date_filter(select(Dispatch), Dispatch.dispatch_date, params)
    if params.get("status"):
        stmt = stmt.where(Dispatch.status == params["status"])
    rows = []
    for d in db.scalars(stmt.options(selectinload(Dispatch.items).selectinload(DispatchItem.production))
                        .order_by(Dispatch.dispatch_date, Dispatch.id).limit(20000)).all():
        o = d.order
        for it in (d.items or [None]):
            rows.append([d.dispatch_no, d.dispatch_date, o.order_no, o.customer.name, o.site.name if o.site else "",
                         o.grade.name if o.grade else "", d.truck.reg_no if d.truck else "", d.mixer.reg_no if d.mixer else "",
                         d.driver_name, d.status, it.production.record_no if it else "", it.production.product_line if it else "",
                         it.bags if it else None, d.planned_m3, d.delivered_m3, d.received_by, reports._dt_local(d.delivered_at),
                         d.remarks])
    data = reports.table_excel("Dispatch", ["Dispatch no.", "Date", "Order no.", "Customer", "Site", "Grade", "Truck",
                                            "Mixer on wheels", "Driver", "Status", "Production record", "Product line", "Bags",
                                            "Planned m³", "Placed m³", "Received by", "Delivered at", "Remarks"], rows, (2,))
    return _file(data, XLSX, f"dispatch-{_stamp(params)}.xlsx")


@router.get("/reports/strength.xlsx")
def strength_xlsx(request: Request, db: Session = Depends(get_db), user: User = Depends(require("reports"))):
    params = dict(request.query_params)
    stmt = _date_filter(select(CubeSample), CubeSample.cast_date, params)
    if params.get("grade", "").isdigit():
        stmt = stmt.where(CubeSample.grade_id == int(params["grade"]))
    rows = []
    for s in db.scalars(stmt.options(selectinload(CubeSample.results)).order_by(CubeSample.cast_date, CubeSample.id)
                        .limit(20000)).all():
        sm = ops.sample_summary(s)
        cust = s.dispatch.order.customer.name if s.dispatch else ""
        for g in sm["groups"]:
            for r in (g["results"] or [None]):
                rows.append([s.sample_no, s.cast_date, s.grade.name if s.grade else "", cust,
                             s.dispatch.dispatch_no if s.dispatch else "", s.specimen_type, s.specimen_size_mm, g["age"],
                             r.test_date if r else None, r.specimen_no if r else "", r.mass_kg if r else None,
                             r.load_kn if r else None, r.strength_mpa if r else None,
                             round(g["mean"], 2) if g["mean"] is not None else None, logic.STRENGTH_LABELS[g["status"]]])
    data = reports.table_excel("Strength tests", ["Sample no.", "Cast date", "Grade", "Customer", "Dispatch no.", "Specimen",
                                                  "Size mm", "Age days", "Test date", "Specimen no.", "Mass kg", "Load kN",
                                                  "Strength MPa", "Mean at age MPa", "Check"], rows, (2, 9))
    return _file(data, XLSX, f"strength-tests-{_stamp(params)}.xlsx")


@router.get("/reports/stock.xlsx")
def stock_xlsx(db: Session = Depends(get_db), user: User = Depends(require("reports"))):
    rows = []
    for ms in ops.raw_stock(db):
        for lb in ms.lots.values():
            rows.append([ms.material.name, ms.material.category, lb.lot, lb.decision, ms.unit, round(lb.received, 3),
                         round(lb.used, 3), round(lb.adjusted, 3), round(lb.balance, 3), lb.last_date])
        if not ms.lots:
            rows.append([ms.material.name, ms.material.category, "", "", ms.unit, 0, 0, 0, 0, None])
    data = reports.table_excel("Raw material stock", ["Material", "Category", "Lot", "Lot decision", "Unit", "Received",
                                                      "Used", "Adjusted", "Balance", "Last movement"], rows, (10,))
    return _file(data, XLSX, f"stock-{config.local_today().isoformat()}.xlsx")


@router.get("/reports/ncr.xlsx")
def ncr_xlsx(request: Request, db: Session = Depends(get_db), user: User = Depends(require("reports"))):
    params = dict(request.query_params)
    stmt = _date_filter(select(NCR), NCR.raised_date, params)
    if params.get("status") == "open":
        stmt = stmt.where(NCR.status != "Closed")
    elif params.get("status"):
        stmt = stmt.where(NCR.status == params["status"])
    rows = [[n.ncr_no, n.raised_date, n.source, n.title, n.description, n.containment, n.root_cause, n.corrective_action,
             n.owner.display if n.owner else "", n.due_date, n.status, n.verification, n.closed_date,
             n.raised_by.display if n.raised_by else ""]
            for n in db.scalars(stmt.order_by(NCR.raised_date, NCR.id)).all()]
    data = reports.table_excel("NCR register", ["NCR no.", "Raised", "Source", "Title", "Description", "Containment",
                                                "Root cause", "Corrective action", "Owner", "Due", "Status", "Verification",
                                                "Closed", "Raised by"], rows, (2, 10, 13))
    return _file(data, XLSX, f"ncr-register-{_stamp(params)}.xlsx")


@router.get("/reports/equipment.xlsx")
def equipment_xlsx(db: Session = Depends(get_db), user: User = Depends(require("reports"))):
    rows = []
    for e in db.scalars(select(Equipment).order_by(Equipment.tag)).all():
        last = e.calibrations[0] if e.calibrations else None
        rows.append([e.tag, e.name, e.location, e.make_model, e.serial_no, e.range_text, e.interval_days, e.status,
                     last.cal_date if last else None, last.result if last else "", last.certificate_no if last else "",
                     last.agency if last else "", e.next_due])
    data = reports.table_excel("Equipment", ["ID / tag", "Name", "Location", "Make / model", "Serial no.", "Range",
                                             "Interval days", "Status", "Last calibrated", "Result", "Certificate no.",
                                             "Agency", "Next due"], rows, (9, 13))
    return _file(data, XLSX, f"equipment-calibration-{config.local_today().isoformat()}.xlsx")


@router.get("/reports/site-mix-dataset.xlsx")
def site_mix_dataset(request: Request, db: Session = Depends(get_db), user: User = Depends(require("reports"))):
    from .. import dataset
    params = dict(request.query_params)
    start, end = parse_period(params.get("from"), params.get("to"))
    cols, rows, notes = dataset.build(db, start, end)
    return _file(dataset.to_excel(cols, rows, notes), XLSX, f"site-mix-dataset-{start}-to-{end}.xlsx")
