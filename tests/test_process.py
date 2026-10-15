"""Coating and grinding batches, bags per order with lot tracing and labels, dispatch of bags, site mixing, stock."""
import re
from datetime import date

from sqlalchemy import select

from app import operations as ops
from app import process
from app import scm_library as scm
from app import standard_sets as sets
from app.db import SessionLocal
from app.models import (
    Customer, Material, Order, Pack, PlantSettings, ProcessBatch, QCTest, Recipe, RecipeComponent, SiteMix, User,
)

TODAY = date.today().isoformat()


def by_name(params):
    return {p.name: p for p in params}


# ---------------------------------------------------------------- standard sets for the new materials

def test_scm_sets():
    g = by_name(scm.ggbs_set("Every lot", "Monthly"))
    assert g["Fineness (Blaine specific surface)"].min == 320
    assert g["Slag activity index, 7 days"].min == 60 and g["Slag activity index, 28 days"].min == 75
    assert g["Magnesium oxide (MgO)"].max == 17.0 and g["Manganese oxide (MnO)"].max == 5.5
    assert g["Glass content"].min == 85 and g["Moisture content"].max == 1.0
    f = by_name(scm.fly_ash_set("Calcareous", "Every lot", "Monthly"))
    assert f["SiO₂ + Al₂O₃ + Fe₂O₃"].min == 50 and f["Silicon dioxide (SiO₂)"].min == 25
    assert by_name(scm.fly_ash_set("Siliceous", "Every lot", "Monthly"))["SiO₂ + Al₂O₃ + Fe₂O₃"].min == 70
    assert f["Lime reactivity (average compressive strength)"].min == 4.5 and f["Total chlorides"].max == 0.05
    s = by_name(scm.silica_fume_set("Every lot", "Monthly"))
    assert s["Silicon dioxide (SiO₂)"].min == 85.0 and s["Specific surface"].min == 15
    assert s["Compressive strength at 7 days, percent of control"].min == 85.0
    a = by_name(scm.admixture_set("Superplasticizing, normal", "Every lot", 40, 2.0, 1.08, 1.0))
    assert (a["Dry material content"].min, a["Dry material content"].max) == (38.0, 42.0)
    assert (a["Relative density"].min, a["Relative density"].max) == (1.06, 1.1)
    assert (a["Chloride ion content"].min, a["Chloride ion content"].max) == (0.8, 1.2)
    assert a["pH"].min == 6
    pp = by_name(scm.synthetic_fibre_set("Polypropylene", "Class II", "Every lot"))
    assert pp["Tensile strength"].min == 300 and (pp["Specific gravity"].min, pp["Specific gravity"].max) == (0.90, 0.91)
    assert pp["Melting temperature"].min == 160 and pp["Glass transition temperature"].max == -10
    assert (pp["Length"].min, pp["Length"].max) == (5, 25)
    pe = by_name(scm.synthetic_fibre_set("Polyester", "Class I", "Every lot"))
    assert pe["Melting temperature"].min == 240 and pe["Glass transition temperature"].min == 60   # Amendment 1
    try:
        sets.build("synfibre", {"fibre_type": "Polypropylene", "phys_freq": "Every lot"})
        raise AssertionError("class should be required for polypropylene")
    except ValueError:
        pass
    assert {s.key for s in sets.sets_for("Fibre")} == {"synfibre"}
    assert "ggbs" in {s.key for s in sets.sets_for("Coating material")}


# ---------------------------------------------------------------- the plant flow

def _setup_data():
    with SessionLocal() as db:
        uid = db.scalars(select(User.id)).first()
        names = {"P 20 mm": "Coarse aggregate", "P M-sand": "Fine aggregate", "P Microsilica": "Coating material",
                 "P Coated 20": "Coated aggregate", "P OPC": "Cement", "P GGBS": "Supplementary cementitious material",
                 "P Fly ash": "Supplementary cementitious material", "P Ground GGBS": "Ground cementitious material",
                 "P PP fibre": "Fibre", "P SP": "Admixture"}
        m = {}
        for n, c in names.items():
            m[n] = Material(name=n, category=c)
            db.add(m[n])
        db.flush()
        lots = {}
        for i, (n, lot, qty, unit, dec) in enumerate([
                ("P 20 mm", "L20", 10, "t", "Accepted"), ("P M-sand", "LMS", 10, "t", "Accepted"),
                ("P Microsilica", "LMSF", 500, "kg", "Accepted"), ("P OPC", "LOPC", 5, "t", "Accepted"),
                ("P GGBS", "LGG", 5, "t", "On hold"), ("P Fly ash", "LFA", 5, "t", "Accepted"),
                ("P PP fibre", "LPP", 50, "kg", "Accepted"), ("P SP", "LSP", 1000, "kg", "Accepted")]):
            t = QCTest(test_no=f"PT-{i:03d}", test_date=date.today(), material_id=m[n].id, material_name=n,
                       category=m[n].category, lot_no=lot, quantity=qty, unit=unit, overall="pass", decision=dec,
                       created_by_id=uid)
            db.add(t)
            db.flush()
            lots[n] = t.id
        r = Recipe(name="P Mix M30", components=[
            RecipeComponent(material_id=m["P Coated 20"].id, quantity=900, unit="kg"),
            RecipeComponent(material_id=m["P M-sand"].id, quantity=700, unit="kg"),
            RecipeComponent(material_id=m["P OPC"].id, quantity=300, unit="kg"),
            RecipeComponent(material_id=m["P Ground GGBS"].id, quantity=100, unit="kg"),
            RecipeComponent(material_id=m["P PP fibre"].id, quantity=0.9, unit="kg"),
            RecipeComponent(material_id=m["P SP"].id, quantity=3, unit="kg")])
        db.add(r)
        cust = Customer(name="P Builders")
        db.add(cust)
        db.flush()
        o1 = Order(order_no="SO-P-1", order_date=date.today(), customer_id=cust.id, recipe_id=r.id, status="Open",
                   created_by_id=uid)
        o2 = Order(order_no="SO-P-2", order_date=date.today(), customer_id=cust.id, status="Open", created_by_id=uid)
        db.add_all([o1, o2])
        s = db.get(PlantSettings, 1) or PlantSettings(id=1)
        import json as _json
        from app.models import TOLERANCE_CATEGORIES
        s.category_tolerances = _json.dumps({c: 2.0 for c in TOLERANCE_CATEGORIES})
        db.add(s)
        db.commit()
        return {k: v.id for k, v in m.items()}, lots, o1.id, o2.id


def _new_id(r, path):
    m = re.search(rf"{path}/(\d+)", r.headers.get("location", ""))
    assert m, (r.status_code, r.headers.get("location"), r.text[:1500])
    return int(m.group(1))


def test_plant_flow(admin):
    mats, lots, oid, oid2 = _setup_data()

    # ---- coating: 1000 kg of 20 mm coated with 20 kg microsilica
    page = admin.get("/process/coating/new").text
    assert f"qc:{lots['P 20 mm']}" in page and "P Coated 20" in page
    r = admin.post("/process/coating/new", {
        "batch_date": TODAY, "output_material_id": mats["P Coated 20"], "output_qty": "1020", "output_unit": "kg",
        "in-0-role": "aggregate", "in-0-lot": f"qc:{lots['P 20 mm']}", "in-0-qty": "1", "in-0-unit": "t",
        "in-1-role": "coating", "in-1-lot": f"qc:{lots['P Microsilica']}", "in-1-qty": "20", "in-1-unit": "kg"})
    coat_id = _new_id(r, "/process/batches")
    with SessionLocal() as db:
        b = db.get(ProcessBatch, coat_id)
        assert b.decision == "On hold" and b.coating_pct == 2.0 and b.output_lot_no == b.batch_no
        assert b.batch_no.startswith("CB-")

    # a coating batch needs both an aggregate and a coating lot
    r = admin.post("/process/coating/new", {
        "batch_date": TODAY, "output_material_id": mats["P Coated 20"],
        "in-0-role": "aggregate", "in-0-lot": f"qc:{lots['P 20 mm']}", "in-0-qty": "1000", "in-0-unit": "kg"})
    assert r.status_code == 400 and "Add at least one coating material lot." in r.text

    # ---- grinding: GGBS lot is on hold, so a remark is required; one material per batch
    base = {"batch_date": TODAY, "output_material_id": mats["P Ground GGBS"], "output_qty": "480", "output_unit": "kg",
            "blaine": "610", "in-0-role": "feed", "in-0-lot": f"qc:{lots['P GGBS']}", "in-0-qty": "500", "in-0-unit": "kg"}
    admin.get("/process/grinding/new")
    r = admin.post("/process/grinding/new", base)
    assert r.status_code == 400 and "Add a remark to use lots that are not accepted" in r.text
    r = admin.post("/process/grinding/new", {**base, "in-1-role": "feed", "in-1-lot": f"qc:{lots['P Fly ash']}",
                                             "in-1-qty": "10", "in-1-unit": "kg", "remarks": "x"})
    assert r.status_code == 400 and "grinds one material" in r.text
    r = admin.post("/process/grinding/new", {**base, "remarks": "Used on hold lot as per QC instruction"})
    grind_id = _new_id(r, "/process/batches")

    # ---- decisions
    admin.get(f"/process/batches/{coat_id}")
    assert admin.post(f"/process/batches/{coat_id}/decision", {"decision": "Accepted"}).status_code == 303
    admin.get(f"/process/batches/{grind_id}")
    r = admin.post(f"/process/batches/{grind_id}/decision", {"decision": "Accepted"})
    assert r.status_code == 400 and "Add a remark to accept its output" in r.text
    assert admin.post(f"/process/batches/{grind_id}/decision",
                      {"decision": "Accepted", "remarks": "Feed lot released later"}).status_code == 303

    # ---- packing per order: the mix design fills the planned quantities
    page = admin.get(f"/packs/new?order_id={oid}&kind=Aggregate+jumbo+bag").text
    assert "P Coated 20" in page and f"pb:{coat_id}" in page and "900" in page
    agg = {"order_id": oid, "kind": "Aggregate jumbo bag", "pack_date": TODAY,
           "it-0-lot": f"pb:{coat_id}", "it-0-actual": "905", "it-0-unit": "kg",
           "it-1-lot": f"qc:{lots['P M-sand']}", "it-1-actual": "700", "it-1-unit": "kg"}
    r = admin.post("/packs/new", {**agg, "it-0-actual": "800"})          # 11 % low: over tolerance
    assert r.status_code == 400 and "quantities outside the batching tolerance" in r.text
    r = admin.post("/packs/new", {**agg, "it-1-lot": "", "it-1-actual": ""})  # M-sand missing
    assert r.status_code == 400 and "materials of the mix design missing" in r.text
    r = admin.post("/packs/new", {**agg, "it-0-lot": f"qc:{lots['P OPC']}"})  # cement is not allowed in this bag
    assert r.status_code == 400 and "Line 1: select a lot from the list." in r.text
    r = admin.post("/packs/new", {**agg, "copies": "2"})
    assert r.status_code == 303
    with SessionLocal() as db:
        aggs = db.scalars(select(Pack).where(Pack.order_id == oid, Pack.kind == "Aggregate jumbo bag")).all()
        assert len(aggs) == 2 and aggs[0].batching_status == "ok" and aggs[0].net_kg == 1605
        assert {i.lot_no for i in aggs[0].items} == {"LMS", db.get(ProcessBatch, coat_id).batch_no}
        dev = {i.material_name: i.dev_pct for i in aggs[0].items}
        assert round(dev["P Coated 20"], 3) == round(5 / 900 * 100, 3)
    r = admin.post("/packs/new", {"order_id": oid, "kind": "Cementitious jumbo bag", "pack_date": TODAY,
                                  "it-0-lot": f"qc:{lots['P OPC']}", "it-0-actual": "300", "it-0-unit": "kg",
                                  "it-1-lot": f"pb:{grind_id}", "it-1-actual": "100", "it-1-unit": "kg"})
    cem_id = _new_id(r, "/packs")
    r = admin.post("/packs/new", {"order_id": oid, "kind": "Fibre bag", "pack_date": TODAY,
                                  "it-0-lot": f"qc:{lots['P PP fibre']}", "it-0-actual": "0.9", "it-0-unit": "kg"})
    fib_id = _new_id(r, "/packs")
    r = admin.post("/packs/new", {"order_id": oid, "kind": "Admixture barrel", "pack_date": TODAY,
                                  "it-0-lot": f"qc:{lots['P SP']}", "it-0-actual": "3", "it-0-unit": "kg"})
    bar_id = _new_id(r, "/packs")
    # a bag for the second order (no mix design: quantities are not checked)
    r = admin.post("/packs/new", {"order_id": oid2, "kind": "Fibre bag", "pack_date": TODAY,
                                  "it-0-lot": f"qc:{lots['P PP fibre']}", "it-0-actual": "2", "it-0-unit": "kg"})
    other_id = _new_id(r, "/packs")

    page = admin.get(f"/packs/{cem_id}").text
    assert "Grinding batch" in page and "LOPC" in page
    assert admin.get(f"/packs/{cem_id}/label.pdf").content.startswith(b"%PDF")
    assert admin.get(f"/packs/{cem_id}/label.pdf?size=a4").content.startswith(b"%PDF")
    assert admin.get(f"/orders/{oid}/labels.pdf").content.startswith(b"%PDF")
    with SessionLocal() as db:
        cem_no = db.get(Pack, cem_id).pack_no
    r = admin.get(f"/packs/scan?code={cem_no.lower()}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/packs/{cem_id}"

    # ---- stock follows the lots
    with SessionLocal() as db:
        st = {ms.material.name: ms for ms in ops.raw_stock(db)}
        coat_no = db.get(ProcessBatch, coat_id).batch_no.lower()
    assert st["P 20 mm"].lots["l20"].used == 1000
    assert st["P Coated 20"].lots[coat_no].received == 1020 and st["P Coated 20"].lots[coat_no].used == 1810
    assert st["P GGBS"].lots["lgg"].used == 500

    # ---- dispatch loads the bags of the order
    admin.get("/dispatch/new")
    r = admin.post("/dispatch/new", {"dispatch_date": TODAY, "order_id": oid, "pack_ids": [str(other_id)]})
    assert r.status_code == 400 and "was packed for another order" in r.text
    with SessionLocal() as db:
        agg_ids = [p.id for p in db.scalars(select(Pack).where(Pack.order_id == oid, Pack.kind == "Aggregate jumbo bag"))]
    load = [str(i) for i in [agg_ids[0], cem_id, fib_id, bar_id]]
    r = admin.post("/dispatch/new", {"dispatch_date": TODAY, "order_id": oid, "pack_ids": load})
    did = _new_id(r, "/dispatch")
    with SessionLocal() as db:
        assert db.get(Pack, cem_id).status == "Loaded" and db.get(Pack, agg_ids[1]).status == "Packed"
    page = admin.get(f"/dispatch/{did}").text
    assert "Record site mixing" in page and cem_no in page
    assert admin.get(f"/dispatch/{did}/note.pdf").content.startswith(b"%PDF")

    # ---- site mixing
    admin.get(f"/site-mix/new?dispatch_id={did}")
    form = {"dispatch_id": did, "mix_date": TODAY, "water_l": "160", "slump_mm": "120", "volume_m3": "0.8",
            "pack_ids": [str(agg_ids[0]), str(cem_id), str(fib_id)],
            "ad-0-pack_id": str(bar_id), "ad-0-dose": "3", "ad-0-unit": "kg"}
    r = admin.post("/site-mix/new", {**form, "pack_ids": [str(agg_ids[1])]})
    assert r.status_code == 400 and "not on this dispatch" in r.text
    r = admin.post("/site-mix/new", form)
    mix_id = _new_id(r, "/site-mix")
    with SessionLocal() as db:
        mix = db.get(SiteMix, mix_id)
        assert db.get(Pack, cem_id).status == "Used at site" and db.get(Pack, bar_id).status == "Loaded"
        s = process.mix_summary(mix)
        assert s["binder_kg"] == 400 and s["aggregate_kg"] == 1605 and s["wb"] == 0.4
    page = admin.get(f"/site-mix/{mix_id}").text
    assert "0.400" in page and "LSP" in page

    # ---- cancelling a dispatch puts its bags back in the plant
    admin.get("/dispatch/new")
    r = admin.post("/dispatch/new", {"dispatch_date": TODAY, "order_id": oid, "pack_ids": [str(agg_ids[1])]})
    did2 = _new_id(r, "/dispatch")
    admin.get(f"/dispatch/{did2}")
    admin.post(f"/dispatch/{did2}/delivery", {"status": "Cancelled"})
    with SessionLocal() as db:
        p = db.get(Pack, agg_ids[1])
        assert p.status == "Packed" and p.dispatch_id is None

    # ---- pages render
    with SessionLocal() as db:
        coat_no, grind_no = db.get(ProcessBatch, coat_id).batch_no, db.get(ProcessBatch, grind_id).batch_no
    coat_page, grind_page = admin.get("/process/coating").text, admin.get("/process/grinding").text
    assert coat_no in coat_page and grind_no not in coat_page
    assert grind_no in grind_page and coat_no not in grind_page
    assert admin.get("/process/batches?kind=grinding", follow_redirects=False).headers["location"] == "/process/grinding"
    assert admin.get("/process/mixing").status_code == 404
    for url in ("/process", "/process/coating", "/process/grinding", "/packs", f"/packs?order={oid}", "/packs/scan",
                f"/process/batches/{grind_id}", f"/orders/{oid}"):
        assert admin.get(url).status_code == 200, url

    # ---- AI review data covers the plant process
    import json as _json
    from datetime import date as _d
    from app import ai
    with SessionLocal() as db:
        d = process.review_data(db, _d(2000, 1, 1), _d(2100, 1, 1), 500)
    assert coat_no in [b["batch_no"] for b in d["coating_batches"]]
    assert grind_no in [b["batch_no"] for b in d["grinding_batches"]]
    assert "coating_pct_entered" in d["coating_batches"][0] and "blaine_m2_per_kg_entered" in d["grinding_batches"][0]
    mix = next(m for m in d["site_mixes"] if m["water_l"] == 160)
    assert mix["water_binder_ratio"] == 0.4 and mix["admixture_doses"][0]["dose"] == 3
    cem = next(b for b in d["bags"] if b["kind"] == "Cementitious jumbo bag" and b["status"] == "Used at site")
    assert cem["site_mix_no"] == mix["mix_no"] and cem["contents"]
    assert d["bag_counts_by_kind_and_status"]["Aggregate jumbo bag"]
    _json.dumps(d, default=str)
    assert "Site mixing" in ai.PROMPT and "grinding batches" in ai.PROMPT


def test_set_page_for_new_categories(admin):
    with SessionLocal() as db:
        m = Material(name="P Admix X", category="Admixture")
        db.add(m)
        db.commit()
        mid = m.id
    page = admin.get(f"/setup/materials/{mid}/set").text   # only one set for admixtures: shown directly
    assert "Stated dry material content" in page
    r = admin.post(f"/setup/materials/{mid}/set", {"set": "admixture", "ad_type": "Retarding", "phys_freq": "Every lot",
                                                    "dmc": "30", "rd": "1.15"})
    assert r.status_code == 303
    with SessionLocal() as db:
        p = {x.name: x for x in db.get(Material, mid).parameters}
    assert (p["Dry material content"].min_value, p["Dry material content"].max_value) == (28.5, 31.5)
    assert p["Ash content"].min_value is None
