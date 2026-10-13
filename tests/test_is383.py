"""IS 383 test sets, IS 2386 worksheets and the Table 9 zone rule."""
import json
import re

import pytest
from sqlalchemy import select

from app import is_library as lib
from app.db import SessionLocal
from app.models import Material, QCParameter, QCTest


def by_name(params):
    return {p.name: p for p in params}


# ---------------------------------------------------------------- limits from IS 383:2016

def test_coarse_set_limits_other_concrete():
    p = by_name(lib.coarse_set("Crushed", "Graded 20 mm", "other", m65=False, frost=False))
    assert (p["Passing 40 mm sieve"].min, p["Passing 40 mm sieve"].max) == (100, 100)
    assert (p["Passing 20 mm sieve"].min, p["Passing 20 mm sieve"].max) == (90, 100)
    assert (p["Passing 10 mm sieve"].min, p["Passing 10 mm sieve"].max) == (25, 55)
    assert (p["Passing 4.75 mm sieve"].min, p["Passing 4.75 mm sieve"].max) == (0, 10)
    assert p["Material finer than 75 µm"].max == 1.00
    assert p["Total deleterious materials (excluding mica)"].max == 2.00
    assert p["Soft fragments"].max is None and "Enter the limit" in p["Soft fragments"].note
    assert p["Combined flakiness and elongation index"].max == 40
    assert p["Aggregate crushing value"].max is None
    assert p["Ten per cent fines value"].min == 50 and p["Ten per cent fines value"].unit == "kN"
    assert p["Aggregate impact value"].max == 45
    assert p["Los Angeles abrasion value"].max == 50
    assert "Soundness, sodium sulphate (5 cycles)" not in p
    assert p["Water absorption"].max is None


def test_coarse_set_wearing_m65_frost_manufactured():
    p = by_name(lib.coarse_set("Manufactured", "Single-sized 10 mm", "wearing", m65=True, frost=True))
    assert p["Aggregate crushing value"].max == 22
    assert p["Aggregate impact value"].max == 22
    assert p["Los Angeles abrasion value"].max == 30
    assert "Ten per cent fines value" not in p
    assert p["Soundness, sodium sulphate (5 cycles)"].max == 12
    assert p["Soundness, magnesium sulphate (5 cycles)"].max == 18
    assert p["Water absorption"].max == 5
    assert (p["Specific gravity (oven-dry)"].min, p["Specific gravity (oven-dry)"].max) == (2.1, 3.2)
    assert p["Soft fragments"].max is None and "Enter the limit" in p["Soft fragments"].note
    assert (p["Passing 2.36 mm sieve"].min, p["Passing 2.36 mm sieve"].max) == (0, 5)
    w = by_name(lib.coarse_set("Uncrushed", "Graded 40 mm", "wearing", m65=False, frost=False))
    assert w["Aggregate crushing value"].max == 30 and w["Aggregate impact value"].max == 30
    assert w["Total deleterious materials (excluding mica)"].max == 5.00


def test_fine_set_limits():
    p = by_name(lib.fine_set("Uncrushed (natural sand)", "Zone II", frost=True))
    assert (p["Passing 600 µm sieve"].min, p["Passing 600 µm sieve"].max) == (35, 59)
    assert (p["Passing 150 µm sieve"].min, p["Passing 150 µm sieve"].max) == (0, 10)
    assert p["Material finer than 75 µm"].max == 3.00
    assert p["Shale"].max is None and "Enter the limit" in p["Shale"].note
    assert p["Total deleterious materials (excluding mica)"].max == 5.00
    assert p["Organic impurities (colour test)"].value_type == "passfail"
    assert p["Soundness, sodium sulphate (5 cycles)"].max == 10
    assert p["Soundness, magnesium sulphate (5 cycles)"].max == 15
    assert "Fineness modulus" in p and "Bulking of sand" in p
    c = by_name(lib.fine_set("Crushed stone sand", "Zone II", frost=False))
    assert c["Passing 150 µm sieve"].max == 20
    assert c["Material finer than 75 µm"].max == 15.00
    assert c["Total deleterious materials (excluding mica)"].max == 2.00
    assert by_name(lib.fine_set("Mixed sand", "Zone I", False))["Material finer than 75 µm"].max == 12.00
    assert by_name(lib.fine_set("Manufactured", "Zone IV", False))["Material finer than 75 µm"].max == 10.00


def test_table_values_are_internally_consistent():
    for name, rows in lib.COARSE_GRADING.items():
        for mm, (lo, hi) in rows.items():
            assert 0 <= lo <= hi <= 100, (name, mm)
    for zone, rows in lib.FINE_ZONES.items():
        assert list(rows) == lib.FINE_SIEVES
        for lo, hi in rows.values():
            assert 0 <= lo <= hi <= 100
    with pytest.raises(ValueError):
        lib.coarse_set("Crushed", "Graded 25 mm", "other", False, False)


# ---------------------------------------------------------------- IS 2386 worksheets

def test_worksheet_formulas():
    assert lib.run_calc("finer75", {"B": 500, "C": 485})["value"] == 3.0
    assert lib.run_calc("claylumps", {"W": 200, "R": 198})["value"] == 1.0
    assert lib.run_calc("lightweight", {"W1": 1.5, "W2": 300})["value"] == 0.5
    assert lib.run_calc("crushing", {"A": 3000, "B": 690})["value"] == 23.0
    assert lib.run_calc("impact", {"A": 350, "B": 56})["value"] == 16.0
    assert lib.run_calc("abrasion", {"A": 5000, "B": 3900})["value"] == 22.0
    assert lib.run_calc("ten_fines", {"x": 100, "y": 10})["value"] == 100.0
    s = lib.run_calc("shape", {"M": 1000, "F": 150, "E": 170})
    assert (s["flakiness"], s["elongation"], s["combined"]) == (15.0, 20.0, 35.0)
    b = lib.run_calc("sg_basket", {"A1": 2700, "A2": 950, "B": 2850, "C": 2830})   # A = 1750
    assert b["sg"] == round(2830 / (2850 - 1750), 3) and b["apparent"] == round(2830 / (2830 - 1750), 3)
    assert b["absorption"] == round(100 * 20 / 2830, 2)
    pyc = lib.run_calc("sg_pycnometer", {"A": 500, "B": 1810, "C": 1500, "D": 495})   # displaced 190
    assert pyc["sg"] == round(495 / 190, 3) and pyc["apparent"] == round(495 / 185, 3) and pyc["absorption"] == round(500 / 495 * 100 - 100, 2)
    assert lib.run_calc("bulk_density", {"W": 15.9, "V": 10})["value"] == 1.59
    assert lib.run_calc("voids", {"G": 2.65, "Y": 1.59})["value"] == 40.0
    assert lib.run_calc("bulking", {"h": 125, "h2": 100})["value"] == 25.0
    with pytest.raises(ValueError, match="Enter C"):
        lib.run_calc("finer75", {"B": 500})
    with pytest.raises(ValueError, match="cannot be zero"):
        lib.run_calc("crushing", {"A": 0, "B": 1})


def test_sieve_analysis_and_fm():
    r = lib.sieve_analysis({10: 0, 4.75: 30, 2.36: 70, 1.18: 120, 0.6: 150, 0.3: 80, 0.15: 40}, total=500)
    assert r["passing"] == {10: 100, 4.75: 94, 2.36: 80, 1.18: 56, 0.6: 26, 0.3: 10, 0.15: 2}
    # cumulative retained %: 0, 6, 20, 44, 74, 90, 98 -> sum 332 -> FM 3.32
    assert r["fm"] == 3.32
    with pytest.raises(ValueError):
        lib.sieve_analysis({})


def test_zone_rule():
    zone2 = {10: 100, 4.75: 95, 2.36: 85, 1.18: 70, 0.6: 45, 0.3: 15, 0.15: 5}
    res = {z["zone"]: z for z in lib.classify_zone(zone2)}
    assert res["Zone II"]["within"] and not res["Zone I"]["within"]
    near = {**zone2, 2.36: 72}          # 3 below Zone II minimum: within tolerance
    assert {z["zone"]: z for z in lib.classify_zone(near)}["Zone II"]["within"]
    far = {**zone2, 2.36: 68}           # 7 below: outside
    assert not {z["zone"]: z for z in lib.classify_zone(far)}["Zone II"]["within"]
    s600 = {**zone2, 0.6: 33}           # no tolerance at 600 µm
    assert not {z["zone"]: z for z in lib.classify_zone(s600)}["Zone II"]["within"]
    cum = {**zone2, 2.36: 71, 1.18: 51, 0.3: 34}   # 4 + 4 + 4 = 12 > 10
    assert not {z["zone"]: z for z in lib.classify_zone(cum)}["Zone II"]["within"]
    crushed = {**zone2, 0.15: 18}
    assert not {z["zone"]: z for z in lib.classify_zone(crushed)}["Zone II"]["within"]
    assert {z["zone"]: z for z in lib.classify_zone(crushed, crushed=True)}["Zone II"]["within"]


# ---------------------------------------------------------------- through the app

def test_apply_set_and_record_test(admin):
    admin.get("/setup/materials/new")
    admin.post("/setup/materials/new", {"name": "IS fixture sand", "category": "Fine aggregate", "stock_unit": "t"})
    with SessionLocal() as db:
        mid = db.scalars(select(Material).where(Material.name == "IS fixture sand")).one().id
    page = admin.get(f"/setup/materials/{mid}/is383?preview=1&source=Uncrushed+%28natural+sand%29&zone=Zone+II").text
    assert "Passing 600 µm sieve" in page and "35 – 59 %" in page
    r = admin.post(f"/setup/materials/{mid}/is383", {"source": "Uncrushed (natural sand)", "zone": "Zone II"})
    assert r.status_code == 303
    with SessionLocal() as db:
        params = {p.name: p for p in db.scalars(select(QCParameter).where(QCParameter.material_id == mid)).all()}
    assert len(params) == len(lib.fine_set("Uncrushed (natural sand)", "Zone II", False))
    assert params["Passing 600 µm sieve"].group_name == "Grading" and params["Passing 600 µm sieve"].sieve_mm == 0.6
    # applying again updates rather than duplicates
    admin.get(f"/setup/materials/{mid}/is383")
    admin.post(f"/setup/materials/{mid}/is383", {"source": "Uncrushed (natural sand)", "zone": "Zone III"})
    with SessionLocal() as db:
        again = {p.name: p for p in db.scalars(select(QCParameter).where(QCParameter.material_id == mid)).all()}
    assert len(again) == len(params) and (again["Passing 600 µm sieve"].min_value, again["Passing 600 µm sieve"].max_value) == (60, 79)
    admin.get(f"/setup/materials/{mid}/is383")
    admin.post(f"/setup/materials/{mid}/is383", {"source": "Uncrushed (natural sand)", "zone": "Zone II"})

    # worksheet endpoint
    admin.get("/qc/new")
    r = admin.post("/qc/calc", {"calc": "sieve", "fine": "1", "total": "500", "r_10": "0", "r_4.75": "25", "r_2.36": "50",
                                "r_1.18": "75", "r_0.6": "125", "r_0.3": "150", "r_0.15": "50"})
    res = json.loads(r.text)["result"]
    assert res["passing"] == {"10": 100, "4.75": 95, "2.36": 85, "1.18": 70, "0.6": 45, "0.3": 15, "0.15": 5}
    assert any(z["zone"] == "Zone II" and z["within"] for z in res["zones"])
    r = admin.post("/qc/calc", {"calc": "crushing", "in_A": "x", "in_B": "1"})
    assert r.status_code == 400 and "numbers" in json.loads(r.text)["error"]

    # record a test: grading + a few lot tests, periodic ones left empty, organic impurities pass
    g = {name: params[name].id for name in params}
    data = {"test_date": "2026-10-13", "material_id": mid, "lot_no": "SAND-1", "decision": "Accepted",
            "quantity": "20", "unit": "t"}
    for sieve, v in (("10 mm", 100), ("4.75 mm", 95), ("2.36 mm", 85), ("1.18 mm", 70), ("600 µm", 45),
                     ("300 µm", 15), ("150 µm", 5)):
        data[f"p_{g['Passing ' + sieve + ' sieve']}"] = str(v)
    data[f"p_{g['Fineness modulus']}"] = "2.85"
    data[f"w_{g['Fineness modulus']}"] = json.dumps({"calc": "sieve", "inputs": {"total": 500}, "results": {"fm": 2.85}})
    data[f"p_{g['Organic impurities (colour test)']}"] = "pass"
    admin.get("/qc/new")
    r = admin.post("/qc/new", data)
    assert r.status_code == 303, re.findall(r"<li>(.*?)</li>", r.text)
    tid = int(r.headers["location"].rsplit("/", 1)[1])
    with SessionLocal() as db:
        t = db.get(QCTest, tid)
        st = {x.name: x.status for x in t.results}
        assert t.overall == "pass"                       # periodic tests left empty do not make it incomplete
        assert st["Clay lumps"] == "skipped" and st["Organic impurities (colour test)"] == "pass"
        assert next(x for x in t.results if x.name == "Fineness modulus").workings
    page = admin.get(f"/qc/{tid}").text
    assert "Table 9 zone check" in page and "within Zone II" in page and "Not tested (periodic)" in page
    assert "Workings" in page and "Pass required" in page
    assert admin.get(f"/qc/{tid}/report.pdf").content.startswith(b"%PDF")

    # organic impurities fail -> overall fail
    data[f"p_{g['Organic impurities (colour test)']}"] = "fail"
    data["decision"] = "On hold"
    admin.get("/qc/new")
    r = admin.post("/qc/new", data)
    tid2 = int(r.headers["location"].rsplit("/", 1)[1])
    with SessionLocal() as db:
        assert db.get(QCTest, tid2).overall == "fail"


def test_coarse_set_only_for_aggregates(admin):
    with SessionLocal() as db:
        cement = db.scalars(select(Material).where(Material.category == "Cement")).first()
    r = admin.c.get(f"/setup/materials/{cement.id}/is383", follow_redirects=False)
    assert r.status_code == 303
