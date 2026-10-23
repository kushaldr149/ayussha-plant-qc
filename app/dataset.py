"""One row per site mix, joining the whole chain: product and mix design, bags and their contents, raw-material lot
test results, coating/grinding batch values, admixture doses, site mixing values, sensor readings, strength and
durability results. Values are copied from saved records; the only calculations are sums of bag contents, kg-weighted
means where several lots of one material were used, and min/mean/max of sensor readings.
"""
from __future__ import annotations

import io
import re
from collections import defaultdict

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import durability as du
from . import logic
from . import operations as ops
from . import process
from . import sensors as sn
from .models import Pack, ProcessBatch, QCTest, SiteMix

BASE = [
    ("Site mix no.", "Site mixing record"), ("Mix date", "Site mixing record"), ("Dispatch no.", "Dispatch"),
    ("Order no.", "Order"), ("Customer", "Order"), ("Site", "Order"), ("Product line", "Mix design of the order"),
    ("Product", "Product line, part before the grade"), ("Grade", "Product line, last part (M60 ... M150)"),
    ("Mix design", "Mix design of the order"), ("Element", "Site mixing record"), ("Volume m3", "Site mixing record"),
    ("Water L", "Site mixing record"), ("Binder kg (from bags)", "Sum of cementitious bag contents used"),
    ("Aggregate kg (from bags)", "Sum of aggregate bag contents used"),
    ("Water/binder", "Water L taken as kg ÷ binder kg from bags"), ("Mixing time min", "Site mixing record"),
    ("Slump mm", "Site mixing record"), ("Flow mm", "Site mixing record"), ("Concrete temp C", "Site mixing record"),
    ("Ambient temp C", "Site mixing record"), ("Bags used", "Bags mixed in this site mix"),
    ("Flagged bags", "Bags outside batching tolerance or with lots not accepted"),
    ("Cube sample no.", "Strength sample cast from this mix"), ("Strength check", "Acceptance check of the sample"),
]
# Order of the variable column groups, and what each contains.
GROUPS = [
    ("Qty · ", "Quantity of the material in the bags used, summed (kg, or L for liquids)"),
    ("Lots · ", "Lot numbers of the material in the bags used"),
    ("Lot test · ", "Raw-material test result of the lots used (kg-weighted mean when several lots)"),
    ("Batch · ", "Coating or grinding batch value of the material used (kg-weighted mean when several batches)"),
    ("Admixture dose · ", "Admixture dosed at site, summed"),
    ("Site sensor · ", "Sensor readings attached to the site mix"),
    ("Batch sensor · ", "Sensor readings attached to the coating/grinding batches used (mean of batch means)"),
    ("Strength · ", "Cube strength results by age"),
    ("Durability · ", "Durability results on the strength sample (latest result per test)"),
]
_LINE = re.compile(r"^(.*?)\s+(M\d+)$")


def split_line(line: str) -> tuple[str, str]:
    m = _LINE.match(line or "")
    return (m.group(1), m.group(2)) if m else ("", "")


def _wmean(pairs):
    pairs = [(v, w) for v, w in pairs if v is not None]
    if not pairs:
        return None
    tw = sum(w for _, w in pairs if w)
    if tw:
        return round(sum(v * w for v, w in pairs if w) / tw, 4)
    return round(sum(v for v, _ in pairs) / len(pairs), 4)


def build(db: Session, date_from, date_to) -> tuple[list[str], list[dict], dict[str, str]]:
    mixes = db.scalars(select(SiteMix).where(SiteMix.mix_date >= date_from, SiteMix.mix_date <= date_to)
                       .options(selectinload(SiteMix.packs).selectinload(Pack.items), selectinload(SiteMix.admixtures))
                       .order_by(SiteMix.mix_date, SiteMix.id)).all()
    rows: list[dict] = []
    seen: dict[str, None] = {}
    for m in mixes:
        d, o = m.dispatch, m.dispatch.order
        line = o.recipe.product_line if o.recipe else ""
        product, grade = split_line(line)
        s = process.mix_summary(m)
        sample = m.cube_sample
        sm = ops.sample_summary(sample) if sample else None
        row = {
            "Site mix no.": m.mix_no, "Mix date": m.mix_date, "Dispatch no.": d.dispatch_no, "Order no.": o.order_no,
            "Customer": o.customer.name, "Site": o.site.name if o.site else "", "Product line": line,
            "Product": product, "Grade": grade, "Mix design": o.recipe.name if o.recipe else "",
            "Element": m.element, "Volume m3": m.volume_m3, "Water L": m.water_l,
            "Binder kg (from bags)": round(s["binder_kg"], 3), "Aggregate kg (from bags)": round(s["aggregate_kg"], 3),
            "Water/binder": s["wb"], "Mixing time min": m.mixing_time_min, "Slump mm": m.slump_mm, "Flow mm": m.flow_mm,
            "Concrete temp C": m.concrete_temp_c, "Ambient temp C": m.ambient_temp_c,
            "Bags used": ", ".join(p.pack_no for p in m.packs),
            "Flagged bags": ", ".join(p.pack_no for p in m.packs if process.flagged(p)),
            "Cube sample no.": sample.sample_no if sample else "",
            "Strength check": logic.STRENGTH_LABELS.get(sm["status"], sm["status"]) if sm else "",
        }
        qty: dict[str, float] = defaultdict(float)
        lots: dict[str, set] = defaultdict(set)
        lot_vals: dict[str, list] = defaultdict(list)
        batch_vals: dict[str, list] = defaultdict(list)
        batches: dict[int, ProcessBatch] = {}
        for p in m.packs:
            for it in p.items:
                kg = logic.convert(it.actual, it.unit, "kg")
                if kg is not None:
                    qty[f"Qty · {it.material_name} (kg)"] += kg
                else:
                    lt = logic.convert(it.actual, it.unit, "L")
                    if lt is not None:
                        qty[f"Qty · {it.material_name} (L)"] += lt
                if it.lot_no:
                    lots[f"Lots · {it.material_name}"].add(it.lot_no)
                if it.lot_test_id:
                    t = db.get(QCTest, it.lot_test_id)
                    for r in (t.results if t else []):
                        if r.value is not None and (r.value_type or "number") == "number":
                            unit = f" ({r.unit})" if r.unit else ""
                            lot_vals[f"Lot test · {it.material_name} · {r.name}{unit}"].append((r.value, kg))
                if it.batch_id:
                    b = batches.get(it.batch_id) or db.get(ProcessBatch, it.batch_id)
                    if b:
                        batches[b.id] = b
                        if b.coating_pct is not None:
                            batch_vals[f"Batch · {it.material_name} · coating % of aggregate"].append((b.coating_pct, kg))
                        if b.blaine_m2kg is not None:
                            batch_vals[f"Batch · {it.material_name} · Blaine (m²/kg)"].append((b.blaine_m2kg, kg))
                        if b.residue45_pct is not None:
                            batch_vals[f"Batch · {it.material_name} · residue on 45 micron (%)"].append((b.residue45_pct, kg))
        row.update({k: round(v, 3) for k, v in qty.items()})
        row.update({k: ", ".join(sorted(v)) for k, v in lots.items()})
        row.update({k: _wmean(v) for k, v in lot_vals.items()})
        row.update({k: _wmean(v) for k, v in batch_vals.items()})
        doses: dict[str, float] = defaultdict(float)
        for a in m.admixtures:
            product_name = ", ".join(it.material_name for it in a.pack.items) or a.pack.pack_no
            doses[f"Admixture dose · {product_name} ({a.unit})"] += a.dose
        row.update(doses)
        for x in sn.readings_for(db, m.mix_no, "sitemix", m.started_at, m.finished_at):
            sen, u = x["sensor"], f" ({x['sensor'].unit})" if x["sensor"].unit else ""
            row[f"Site sensor · {sen.tag} · mean{u}"] = round(x["mean"], 4)
            row[f"Site sensor · {sen.tag} · min{u}"] = x["min"]
            row[f"Site sensor · {sen.tag} · max{u}"] = x["max"]
            row[f"Site sensor · {sen.tag} · outside limits"] = x["outside"]
        bmeans: dict[str, list] = defaultdict(list)
        for b in batches.values():
            for x in sn.readings_for(db, b.batch_no, b.kind, b.started_at, b.finished_at):
                u = f" ({x['sensor'].unit})" if x["sensor"].unit else ""
                bmeans[f"Batch sensor · {b.kind} · {x['sensor'].tag} · mean{u}"].append(x["mean"])
        row.update({k: round(sum(v) / len(v), 4) for k, v in bmeans.items()})
        if sm:
            for g in sm["groups"]:
                if g["results"]:
                    row[f"Strength · {g['age']} d · mean MPa"] = round(g["mean"], 2)
                    row[f"Strength · {g['age']} d · lowest MPa"] = round(g["min"], 2)
                    row[f"Strength · {g['age']} d · specimens"] = g["n"]
            for r in du.results_for(db, sample.id):
                u = f" ({r.unit})" if r.unit else ""
                row[f"Durability · {r.test_name} · mean{u}"] = r.mean_value
                row[f"Durability · {r.test_name} · age d"] = r.age_days
                row[f"Durability · {r.test_name} · check"] = du.RESULT_LABELS[r.result]
        rows.append(row)
        for k in row:
            seen.setdefault(k, None)
    base = [c for c, _ in BASE]
    extra = [k for k in seen if k not in base]
    order = {p: i for i, (p, _) in enumerate(GROUPS)}
    extra.sort(key=lambda k: (next((order[p] for p in order if k.startswith(p)), 99), k))
    notes = dict(BASE)
    for k in extra:
        notes[k] = next((n for p, n in GROUPS if k.startswith(p)), "")
    return base + extra, rows, notes


def to_excel(columns: list[str], rows: list[dict], notes: dict[str, str]) -> bytes:
    from .reports import _sheet
    wb = Workbook()
    wb.remove(wb.active)
    ws = _sheet(wb, "Site mixes", columns, [[r.get(c) for c in columns] for r in rows])
    for row in ws.iter_rows(min_row=2, min_col=2, max_col=2):
        for cell in row:
            cell.number_format = "dd-mmm-yyyy"
    _sheet(wb, "Column notes", ["Column", "Source"], [[c, notes.get(c, "")] for c in columns])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
