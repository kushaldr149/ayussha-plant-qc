"""Reports page, PDF documents, Excel exports and AI review."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import ai, audit, config, reports, services
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
    qn, pn = len(data["material_tests"]), len(data["production_records"])
    if not qn and not pn:
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
