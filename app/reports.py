"""PDF test reports, batch traceability certificates and Excel exports."""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import config, logic
from .models import PlantSettings, ProductionRecord, QCTest

# A Unicode font is needed for ≥, ≤ and other symbols; DejaVu ships with most Linux systems
# and is installed in the Docker image. Without it, symbols fall back to plain text.
_FONT, _BOLD, _UNICODE = "Helvetica", "Helvetica-Bold", False
for base in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu"):
    regular, bold = Path(base, "DejaVuSans.ttf"), Path(base, "DejaVuSans-Bold.ttf")
    if regular.exists() and bold.exists():
        pdfmetrics.registerFont(TTFont("DejaVu", str(regular)))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(bold)))
        _FONT, _BOLD, _UNICODE = "DejaVu", "DejaVu-Bold", True
        break

INK = colors.HexColor("#18201E")
MUTED = colors.HexColor("#59645F")
LINE = colors.HexColor("#C9D0CC")
HEAD = colors.HexColor("#EEF1EF")
STATUS_COLOR = {"pass": "#2D6937", "fail": "#A1322A", "incomplete": "#865700", "missing": "#59645F", "nolimit": "#59645F"}


def _t(text) -> str:
    """Escape for reportlab paragraphs and replace symbols the fallback font lacks."""
    s = "" if text is None else str(text)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if not _UNICODE:
        s = s.replace("≥", "&gt;=").replace("≤", "&lt;=").replace("–", "-").replace("—", "-").replace("³", "3")
    return s


def _styles():
    base = ParagraphStyle("b", fontName=_FONT, fontSize=9, leading=12, textColor=INK, alignment=TA_LEFT)
    return {
        "body": base,
        "small": ParagraphStyle("s", parent=base, fontSize=7.5, leading=10, textColor=MUTED),
        "title": ParagraphStyle("t", parent=base, fontName=_BOLD, fontSize=14, leading=18, alignment=2),
        "right": ParagraphStyle("r", parent=base, alignment=2),
        "h": ParagraphStyle("h", parent=base, fontName=_BOLD, fontSize=10, leading=14, spaceBefore=6),
        "cell": ParagraphStyle("c", parent=base, fontSize=8.5, leading=11),
        "cellb": ParagraphStyle("cb", parent=base, fontName=_BOLD, fontSize=8.5, leading=11),
    }


def _num(v, digits=4) -> str:
    if v is None:
        return "—"
    return f"{v:,.{digits}f}".rstrip("0").rstrip(".")


def _header(settings: PlantSettings, title: str, ref: str, st) -> list:
    org = settings.company_name or config.APP_NAME
    plant = " · ".join(x for x in (settings.plant_name, settings.plant_address.replace("\n", ", ")) if x)
    left = [Paragraph(_t(org), st["h"])]
    if plant:
        left.append(Paragraph(_t(plant), st["small"]))
    right = [Paragraph(_t(title), st["title"]), Paragraph(_t(ref), st["right"])]
    t = Table([[left, right]], colWidths=[85 * mm, 95 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                           ("LINEBELOW", (0, 0), (-1, 0), 1, INK), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return [t, Spacer(1, 6 * mm)]


def _kv_table(pairs: list[tuple[str, str]], st) -> Table:
    rows = []
    for i in range(0, len(pairs), 2):
        row = []
        for k, v in pairs[i:i + 2]:
            row += [Paragraph(_t(k), st["small"]), Paragraph(_t(v), st["cell"])]
        while len(row) < 4:
            row.append("")
        rows.append(row)
    t = Table(rows, colWidths=[30 * mm, 60 * mm, 30 * mm, 60 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _grid(data, widths, st, right_cols=()) -> Table:
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [("FONTNAME", (0, 0), (-1, -1), _FONT), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
             ("BACKGROUND", (0, 0), (-1, 0), HEAD), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
             ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    for c in right_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


def _signatures(labels: list[str], st) -> Table:
    """Separate signature lines with a gap between them."""
    gap, n = 10 * mm, len(labels)
    width = (180 * mm - gap * (n - 1)) / n
    cells, widths, style = [], [], [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                    ("TOPPADDING", (0, 0), (-1, -1), 3)]
    for i, lbl in enumerate(labels):
        if i:
            cells.append("")
            widths.append(gap)
        col = len(cells)
        cells.append(Paragraph(_t(lbl), st["small"]))
        widths.append(width)
        style.append(("LINEABOVE", (col, 0), (col, 0), 0.6, INK))
    t = Table([cells], colWidths=widths)
    t.setStyle(TableStyle(style))
    return t


def _footer(note: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont(_FONT, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, 10 * mm, note)
        canvas.drawRightString(195 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()
    return draw


def _build(story, title: str, note: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                            bottomMargin=18 * mm, title=title, author=config.APP_NAME)
    doc.build(story, onFirstPage=_footer(note), onLaterPages=_footer(note))
    return buf.getvalue()


def _generated() -> str:
    return datetime.now(config.TZ).strftime("%d %b %Y %H:%M")


def qc_report_pdf(test: QCTest, settings: PlantSettings) -> bytes:
    st = _styles()
    story = _header(settings, "Material Test Report", test.test_no, st)
    story.append(_kv_table([
        ("Test date", test.test_date.strftime("%d %b %Y")), ("Material", test.material_name),
        ("Category", test.category or "—"), ("Supplier", test.supplier or "—"),
        ("Lot / batch no.", test.lot_no or "—"), ("Vehicle no.", test.vehicle_no or "—"),
        ("Quantity received", f"{_num(test.quantity)} {test.unit}" if test.quantity is not None else "—"),
        ("Tested by", test.created_by.display if test.created_by else "—"),
    ], st))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Test results", st["h"]))
    data = [[Paragraph(_t(h), st["cellb"]) for h in ("Parameter", "Method / reference", "Limit", "Result value", "Status")]]
    for r in test.results:
        color = STATUS_COLOR.get(r.status, "#18201E")
        data.append([
            Paragraph(_t(r.name), st["cell"]), Paragraph(_t(r.method or "—"), st["cell"]),
            Paragraph(_t(logic.limit_text(r.min_value, r.max_value, r.unit)), st["cell"]),
            Paragraph(_t(f"{_num(r.value)} {r.unit}" if r.value is not None else "—"), st["cell"]),
            Paragraph(f'<font color="{color}">{_t(logic.STATUS_LABELS.get(r.status, r.status))}</font>', st["cell"]),
        ])
    story.append(_grid(data, [42 * mm, 46 * mm, 34 * mm, 30 * mm, 28 * mm], st))
    story.append(Spacer(1, 5 * mm))
    story.append(_kv_table([
        ("Overall result", logic.STATUS_LABELS.get(test.overall, test.overall)), ("Decision", test.decision),
        ("Decision by", test.decision_by.display if test.decision_by else "—"),
        ("Decision on", test.decision_at.strftime("%d %b %Y") if test.decision_at else "—"),
    ], st))
    if test.remarks:
        story.append(Paragraph("Remarks", st["h"]))
        story.append(Paragraph(_t(test.remarks).replace("\n", "<br/>"), st["body"]))
    story.append(Spacer(1, 22 * mm))
    story.append(_signatures(["Tested by", "Checked by", "Approved by (Quality)"], st))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(_t("Limits shown are those set in the app when the test was recorded."), st["small"]))
    return _build(story, f"Material Test Report {test.test_no}",
                  f"{config.APP_NAME} · {test.test_no} · generated {_generated()}")


def batch_certificate_pdf(record: ProductionRecord, settings: PlantSettings, tests: dict[int, QCTest]) -> bytes:
    st = _styles()
    story = _header(settings, "Batch Traceability Certificate", record.record_no, st)
    story.append(_kv_table([
        ("Production date", record.prod_date.strftime("%d %b %Y")), ("Shift", record.shift or "—"),
        ("Product line", record.product_line), ("Recipe", record.recipe_name or "—"),
        ("Bags filled", _num(record.bags, 0) if record.bags is not None else "—"),
        ("Target weight per bag", f"{_num(record.bag_target_kg)} kg" if record.bag_target_kg is not None else "—"),
        ("Total actual weight", f"{_num(record.total_actual_kg)} kg" if record.total_actual_kg is not None else "—"),
        ("Batching tolerance", f"± {_num(record.tolerance_pct)} %" if record.tolerance_pct is not None else "Not set"),
    ], st))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Materials and lots used", st["h"]))
    data = [[Paragraph(_t(h), st["cellb"]) for h in
             ("Material", "Lot no.", "QC test", "Lot decision", "Planned", "Actual", "Deviation")]]
    for c in record.components:
        t = tests.get(c.lot_test_id) if c.lot_test_id else None
        dev = f"{c.dev_pct:+.2f} %" if c.dev_pct is not None else "—"
        data.append([
            Paragraph(_t(c.material_name), st["cell"]), Paragraph(_t(c.lot_no or "—"), st["cell"]),
            Paragraph(_t(f"{t.test_no} ({t.test_date:%d %b %Y})" if t else "—"), st["cell"]),
            Paragraph(_t(c.lot_decision or "—"), st["cell"]),
            Paragraph(_t(f"{_num(c.planned)} {c.unit}" if c.planned is not None else "—"), st["cell"]),
            Paragraph(_t(f"{_num(c.actual)} {c.unit}"), st["cell"]), Paragraph(_t(dev), st["cell"]),
        ])
    story.append(_grid(data, [33 * mm, 22 * mm, 31 * mm, 22 * mm, 24 * mm, 24 * mm, 24 * mm], st))
    story.append(Spacer(1, 5 * mm))
    story.append(_kv_table([
        ("Production status", logic.PRODUCTION_LABELS.get(record.status, record.status)),
        ("Largest deviation", f"{_num(record.max_abs_dev_pct, 2)} %" if record.max_abs_dev_pct is not None else "—"),
        ("All lots accepted", "No" if record.lot_issue or any(not c.lot_no for c in record.components) else "Yes"),
        ("Entered by", record.created_by.display if record.created_by else record.source.upper()),
    ], st))
    if record.remarks:
        story.append(Paragraph("Remarks", st["h"]))
        story.append(Paragraph(_t(record.remarks).replace("\n", "<br/>"), st["body"]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(_t(
        "This certificate lists the materials, lots and weights recorded for this production record and the QC "
        "decision on each lot at the time of production. It does not by itself certify compliance with a standard "
        "or specification."), st["small"]))
    story.append(Spacer(1, 22 * mm))
    story.append(_signatures(["Plant operator", "QC / lab", "Approved by (Quality)"], st))
    return _build(story, f"Batch Traceability Certificate {record.record_no}",
                  f"{config.APP_NAME} · {record.record_no} · generated {_generated()}")


# ---------------------------------------------------------------- Excel

def _sheet(wb: Workbook, title: str, headers: list[str], rows: list[list]):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="EEF1EF")
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    for row in rows:
        ws.append(row)
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = ws.dimensions
    for i, h in enumerate(headers, start=1):
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:500] if r[i - 1] is not None])
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, width + 2), 45)
    return ws


def qc_excel(tests: list[QCTest]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    rows = []
    for t in tests:
        for r in (t.results or [None]):
            rows.append([
                t.test_no, t.test_date, t.material_name, t.category, t.supplier, t.lot_no, t.vehicle_no,
                t.quantity, t.unit,
                r.name if r else None, r.method if r else None, r.unit if r else None,
                r.min_value if r else None, r.max_value if r else None, r.value if r else None,
                logic.STATUS_LABELS.get(r.status, r.status) if r else None,
                logic.STATUS_LABELS.get(t.overall, t.overall), t.decision, t.remarks,
                t.created_by.display if t.created_by else "",
            ])
    ws = _sheet(wb, "Material QC", [
        "Test no.", "Test date", "Material", "Category", "Supplier", "Lot no.", "Vehicle no.", "Quantity", "Unit",
        "Parameter", "Method / reference", "Parameter unit", "Min", "Max", "Value", "Result", "Overall",
        "Decision", "Remarks", "Tested by"], rows)
    for row in ws.iter_rows(min_row=2, min_col=2, max_col=2):
        for cell in row:
            cell.number_format = "dd-mmm-yyyy"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def production_excel(records: list[ProductionRecord]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    rows = []
    for r in records:
        for c in (r.components or [None]):
            rows.append([
                r.record_no, r.prod_date, r.shift, r.product_line, r.recipe_name,
                c.material_name if c else None, c.lot_no if c else None, c.lot_decision if c else None,
                c.planned if c else None, c.actual if c else None, c.unit if c else None,
                round(c.dev_pct, 3) if c and c.dev_pct is not None else None,
                r.tolerance_pct, logic.PRODUCTION_LABELS.get(r.status, r.status), r.bags, r.bag_target_kg,
                r.total_actual_kg, r.remarks, r.source, r.created_by.display if r.created_by else "",
            ])
    ws = _sheet(wb, "Production log", [
        "Record no.", "Date", "Shift", "Product line", "Recipe", "Material", "Lot no.", "Lot decision",
        "Planned", "Actual", "Unit", "Deviation %", "Tolerance %", "Status", "Bags", "Target per bag kg",
        "Total actual kg", "Remarks", "Source", "Entered by"], rows)
    for row in ws.iter_rows(min_row=2, min_col=2, max_col=2):
        for cell in row:
            cell.number_format = "dd-mmm-yyyy"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
