"""Cement test sets (IS 269, IS 1489 Part 1, IS 455) and the standard materials page."""
import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import cement_library as cem
from app.db import SessionLocal
from app.models import Material


def by_name(params):
    return {p.name: p for p in params}


def test_opc_limits():
    p43 = by_name(cem.cement_set("OPC 43", "Every lot", "When required"))
    p53 = by_name(cem.cement_set("OPC 53", "Every lot", "When required"))
    s28 = "Compressive strength, 28 days (672 ± 4 h)"
    assert (p43[s28].min, p43[s28].max) == (43, 58)
    assert (p53[s28].min, p53[s28].max) == (53, None)
    assert p43["Compressive strength, 3 days (72 ± 1 h)"].min == 23 and p53["Compressive strength, 3 days (72 ± 1 h)"].min == 27
    assert p43["Compressive strength, 7 days (168 ± 2 h)"].min == 33 and p53["Compressive strength, 7 days (168 ± 2 h)"].min == 37
    assert (p43["Lime saturation factor"].min, p43["Lime saturation factor"].max) == (0.66, 1.02)
    assert (p53["Lime saturation factor"].min, p53["Lime saturation factor"].max) == (0.80, 1.02)
    assert p43["Loss on ignition"].max == 5.0 and p53["Loss on ignition"].max == 4.0
    for p in (p43, p53):
        assert p["Fineness (Blaine specific surface)"].min == 225
        assert p["Insoluble residue"].max == 5.0 and p["Magnesia (MgO)"].max == 6.0
        assert p["Total sulphur as SO₃"].max == 3.5 and p["Chloride content"].max == 0.1
        assert p["Initial setting time"].min == 30 and p["Final setting time"].max == 600
        assert p["Soundness, Le Chatelier expansion"].max == 10 and p["Soundness, autoclave expansion"].max == 0.8
        assert p["Alkali content (Na₂O + 0.658 K₂O)"].max is None
    assert p43["Fineness (Blaine specific surface)"].frequency == "Every lot"
    assert p43["Magnesia (MgO)"].frequency == "When required"
    assert "IS 269:2015" in p43["Magnesia (MgO)"].method_text


def test_ppc_psc_limits():
    ppc = by_name(cem.cement_set("PPC", "Every lot", "Monthly", 30))
    assert ppc["Fineness (Blaine specific surface)"].min == 300
    assert ppc["Drying shrinkage"].max == 0.15
    assert (ppc["Insoluble residue"].min, ppc["Insoluble residue"].max) == (18.0, 32.8)  # 0.6x ; x + 4(100-x)/100
    assert ppc["Magnesia (MgO)"].max == 6.0 and ppc["Total sulphur as SO₃"].max == 3.5
    assert (ppc["Fly ash content (declared)"].min, ppc["Fly ash content (declared)"].max) == (15, 35)
    assert "IS 1489 (Part 1):2015 Table 2" in ppc["Fineness (Blaine specific surface)"].method_text
    assert ppc["Insoluble residue"].frequency == "Monthly"
    no_x = by_name(cem.cement_set("PPC", "Every lot", "Monthly"))
    assert no_x["Insoluble residue"].max is None and "declared fly ash" in no_x["Insoluble residue"].note
    with pytest.raises(ValueError):
        cem.cement_set("PPC", "Every lot", "Monthly", 40)
    psc = by_name(cem.cement_set("PSC", "Every lot", "Monthly"))
    assert psc["Fineness (Blaine specific surface)"].min == 225 and "Drying shrinkage" not in psc
    assert psc["Insoluble residue"].max == 4.0 and psc["Magnesia (MgO)"].max == 10.0
    assert psc["Sulphide sulphur (S)"].max == 1.5 and psc["Loss on ignition"].max == 5.0
    assert (psc["Granulated slag content (declared)"].min, psc["Granulated slag content (declared)"].max) == (25, 70)
    assert psc["Compressive strength, 28 days (672 ± 4 h)"].min == 33
    with pytest.raises(ValueError):
        cem.cement_set("PSC", "Every lot", "Monthly", 80)


def _mat(name):
    with SessionLocal() as db:
        m = db.scalars(select(Material).where(Material.name == name).options(selectinload(Material.parameters))).first()
        return (m, {p.name: p for p in m.parameters}) if m else (None, {})


def test_standard_materials_page(admin):
    page = admin.get("/setup/standard-materials").text
    for name in ("20 mm down", "12.5 mm down", "M-sand", "OPC-43 grade", "OPC-53 grade", "PPC", "PSC"):
        assert f'value="{name}"' in page
    # Nothing chosen: every ticked row must report its missing options and nothing is created.
    data = {f"{k}_on": "on" for k in ("ca20", "msand", "opc43")}
    r = admin.post("/setup/standard-materials", data)
    assert r.status_code == 400
    assert "20 mm down: select the type of coarse aggregate" in r.text
    assert "M-sand: select the type of fine aggregate" in r.text
    assert "OPC-43 grade: how often your lab runs the physical tests: select or enter a value." in r.text
    assert _mat("20 mm down")[0] is None

    data = {
        "ca20_on": "on", "ca20_name": "20 mm down", "ca20_source": "Crushed", "ca20_grading": "Graded 20 mm", "ca20_use": "other",
        "ca12_on": "on", "ca12_name": "12.5 mm down", "ca12_source": "Crushed", "ca12_grading": "Single-sized 12.5 mm",
        "ca12_use": "other",
        "msand_on": "on", "msand_name": "M-sand", "msand_source": "Crushed stone sand", "msand_zone": "Zone II", "msand_mica": "no_tests",
        "opc43_on": "on", "opc43_name": "OPC-43 grade", "opc53_on": "on", "opc53_name": "OPC-53 grade",
        "ppc_on": "on", "ppc_name": "PPC", "ppc_declared": "30", "psc_on": "on", "psc_name": "PSC",
        "phys_freq": "Every lot", "chem_freq": "When required",
    }
    admin.get("/setup/standard-materials")
    r = admin.post("/setup/standard-materials", data)
    assert r.status_code == 303, r.text[:2000]
    m, p = _mat("20 mm down")
    assert m.category == "Coarse aggregate" and (p["Passing 10 mm sieve"].min_value, p["Passing 10 mm sieve"].max_value) == (25, 55)
    m, p = _mat("12.5 mm down")
    assert (p["Passing 10 mm sieve"].min_value, p["Passing 10 mm sieve"].max_value) == (0, 45)
    m, p = _mat("M-sand")
    assert m.category == "Fine aggregate" and p["Material finer than 75 µm"].max_value == 15.00
    assert p["Passing 150 µm sieve"].max_value == 20
    m, p = _mat("OPC-53 grade")
    assert m.category == "Cement" and p["Loss on ignition"].max_value == 4.0
    m, p = _mat("PPC")
    assert p["Insoluble residue"].max_value == 32.8
    m, p = _mat("PSC")
    assert p["Magnesia (MgO)"].max_value == 10.0
    setup = admin.get("/setup").text
    assert "/set\">IS test set" in setup

    # Running it again applies the sets to the existing materials instead of failing.
    admin.get("/setup/standard-materials")
    r = admin.post("/setup/standard-materials", {"opc43_on": "on", "opc43_name": "OPC-43 grade",
                                                 "phys_freq": "Every lot", "chem_freq": "Monthly"})
    assert r.status_code == 303
    assert _mat("OPC-43 grade")[1]["Magnesia (MgO)"].frequency == "Monthly"
    # A name already used in another category is refused.
    admin.get("/setup/standard-materials")
    r = admin.post("/setup/standard-materials", {"psc_on": "on", "psc_name": "M-sand",
                                                 "phys_freq": "Every lot", "chem_freq": "Monthly"})
    assert r.status_code == 400 and "already exists in the Fine aggregate category" in r.text


def test_cement_page_preview_and_apply(admin):
    admin.get("/setup/materials/new")
    admin.post("/setup/materials/new", {"name": "Fixture OPC", "category": "Cement", "stock_unit": "kg"})
    m, _ = _mat("Fixture OPC")
    page = admin.get(f"/setup/materials/{m.id}/set?preview=1&set=opc43&phys_freq=Every+lot").text
    assert "How often your lab runs the chemical tests: select or enter a value." in page
    page = admin.get(f"/setup/materials/{m.id}/set?preview=1&set=opc43&phys_freq=Every+lot&chem_freq=Monthly").text
    assert "43 – 58 MPa" in page
    r = admin.post(f"/setup/materials/{m.id}/set", {"set": "opc43", "phys_freq": "Every lot", "chem_freq": "Monthly"})
    assert r.status_code == 303
    assert _mat("Fixture OPC")[1]["Compressive strength, 28 days (672 ± 4 h)"].max_value == 58
    # Not offered for an aggregate material.
    sand, _ = _mat("M-sand")
    r = admin.get(f"/setup/materials/{sand.id}/set", follow_redirects=False)
    assert r.status_code == 303
    r = admin.post(f"/setup/materials/{sand.id}/set", {"set": "opc43", "phys_freq": "Every lot", "chem_freq": "Monthly"})
    assert r.status_code == 303 and "Passing 600 µm sieve" in str(_mat("M-sand")[1].keys())


def test_cement_worksheets():
    from app import is_library as lib
    from app import scm_library as scm
    # IS 4031 Pt 6 cl. 8.1: 250 kN on 70.6 x 70.6 = 50.16 MPa; the low cube (40 kN-> 8 MPa off) is disregarded.
    r = lib.run_calc("cube", {"L1": 70.6, "B1": 70.6, "P1": 250, "L2": 70.6, "B2": 70.6, "P2": 255,
                              "L3": 70.6, "B3": 70.6, "P3": 200})
    assert r["disregarded"] == "cube 3" and r["value"] == 50.5          # mean of 50.16 and 51.16 = 50.66 -> 50.5
    r = lib.run_calc("cube", {"L1": 70.6, "B1": 70.6, "P1": 250, "L2": 70.6, "B2": 70.6, "P2": 252})
    assert r["disregarded"] == "none" and r["value"] == 50.5            # 50.36 -> 50.5
    with pytest.raises(ValueError, match="retest"):
        lib.run_calc("cube", {"L1": 70, "B1": 70, "P1": 100, "L2": 70, "B2": 70, "P2": 200})
    with pytest.raises(ValueError, match="at least two"):
        lib.run_calc("cube", {"L1": 70, "B1": 70, "P1": 100})
    with pytest.raises(ValueError, match="Enter P2"):
        lib.run_calc("cube", {"L1": 70, "B1": 70, "P1": 100, "L2": 70, "B2": 70})
    assert lib.run_calc("consistency", {"W": 112, "C": 400})["value"] == 28.0
    s = lib.run_calc("setting", {"Ti": 92, "Tf": 247.5, "P": 28, "Mc": 400})
    assert (s["initial"], s["final"], s["water_g"]) == (90, 250, 95.2)
    with pytest.raises(ValueError):
        lib.run_calc("setting", {"Ti": 100, "Tf": 50})
    b = lib.run_calc("blaine", {"K": 2.0, "rho": 3.15, "T": 27, "t1": 60, "t2": 61})
    s1, s2 = 521.08 * 2 * 60 ** 0.5 / 3.15, 521.08 * 2 * 61 ** 0.5 / 3.15
    assert b["cm2_per_g"] == round((s1 + s2) / 2 / 10) * 10 and b["value"] == b["cm2_per_g"] / 10
    assert lib.run_calc("blaine", {"K": 2.0, "rho": 3.15, "T": 20, "t1": 60})["cm2_per_g"] == round(524.2 * 2 * 60 ** 0.5 / 3.15 / 10) * 10
    with pytest.raises(ValueError, match="27 ± 2"):
        lib.run_calc("blaine", {"K": 2.0, "rho": 3.15, "T": 24, "t1": 60})
    p = by_name(cem.cement_set("OPC 53", "Every lot", "Monthly"))
    assert p["Fineness (Blaine specific surface)"].calc == "blaine" and p["Standard consistency"].calc == "consistency"
    assert p["Initial setting time"].calc == p["Final setting time"].calc == "setting"
    assert all(p[n].calc == "cube" for n in p if n.startswith("Compressive strength"))
    assert by_name(scm.ggbs_set("Every lot", "Monthly"))["Fineness (Blaine specific surface)"].calc == "blaine"
