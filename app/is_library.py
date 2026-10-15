"""Physical test sets for coarse and fine aggregate from IS 383:2016 and IS 2386.

Sources read for this module (October 2026):
  * IS 383:2016 Coarse and Fine Aggregate for Concrete - Specification (Third Revision), base text.
    Two copies were compared: the BIS-printed PDF (civilapps.in) and the Internet Archive OCR text
    (archive.org/details/gov.in.is.383.2016). The BIS product manual PM/IS 383/3/August 2020 states the
    standard has 2 amendments. Amendment 1 (August 2017, Internet Archive text) changes Table 1 (utilisation of
    manufactured aggregates) and Table 3 row (iii) (water-soluble chloride, 0.04 % max); neither is in these sets.
    Amendment 2 was not available and is NOT reflected here.
  * BIS product manual PM/IS 383/3/August 2020: test method per requirement and testing frequency.
  * IS 2386 Parts 1 to 4 (1963, law.resource.org copies): calculation formulas.

Rules followed:
  * A limit is filled in only where it could be confirmed in the copies of IS 383:2016 read. Table 2 (soft
    fragments, shale, Note 3 mica) was confirmed from the full-resolution BIS page image on archive.org; where
    Table 2 shows "—" for a column, that parameter is not added. Mica is fine aggregate only (Note 3) and the user
    chooses which of its three cases applies.
  * Frequencies are the BIS product manual levels of control, which the manual itself calls
    recommendatory. They can be changed per parameter in Setup.
"""
from __future__ import annotations

from dataclasses import dataclass, field

STANDARD = "IS 383:2016"

FREQUENCIES = ["Every lot", "Monthly", "Quarterly", "Six-monthly", "When required"]
PERIODIC = set(FREQUENCIES) - {"Every lot"}

GROUPS = ["Grading", "Deleterious materials", "Particle shape", "Mechanical properties", "Physical properties",
          "Soundness"]

SOURCES = [
    ("IS 383:2016 (BIS print)", "https://www.civilapps.in/files/Codes/Materials/Aggregates/IS-383-2016-Aggregates%20for%20Concrete.pdf"),
    ("IS 383:2016 (Internet Archive)", "https://archive.org/details/gov.in.is.383.2016"),
    ("BIS product manual for IS 383", "https://www.bis.gov.in/wp-content/uploads/2020/08/PM-IS-383-AUGUST-2020-REVISED-3.pdf"),
    ("IS 2386 Part 1", "https://law.resource.org/pub/in/bis/S03/is.2386.1.1963.pdf"),
    ("IS 2386 Part 2", "https://law.resource.org/pub/in/bis/S03/is.2386.2.1963.pdf"),
    ("IS 2386 Part 3", "https://law.resource.org/pub/in/bis/S03/is.2386.3.1963.pdf"),
    ("IS 2386 Part 4", "https://law.resource.org/pub/in/bis/S03/is.2386.4.1963.pdf"),
]


@dataclass
class Param:
    name: str
    group: str
    unit: str = "%"
    min: float | None = None
    max: float | None = None
    method: str = ""
    clause: str = ""
    frequency: str = "Every lot"
    calc: str = ""            # key of a worksheet in CALCS, or "sieve"
    value_type: str = "number"  # number / passfail
    sieve_mm: float | None = None
    note: str = ""
    standard: str = STANDARD

    @property
    def method_text(self) -> str:
        return " · ".join(x for x in (self.method, f"{self.standard} {self.clause}" if self.clause else "") if x)


# ---------------------------------------------------------------- grading tables

def sieve_label(mm: float) -> str:
    return f"{int(mm * 1000)} µm" if mm < 1 else (f"{mm:g} mm")


# IS 383:2016 Table 7 (cl. 6.1, 6.2). Values: sieve mm -> (min, max) percent passing.
COARSE_GRADING = {
    "Single-sized 63 mm": {80: (100, 100), 63: (85, 100), 40: (0, 30), 20: (0, 5), 10: (0, 5)},
    "Single-sized 40 mm": {63: (100, 100), 40: (85, 100), 20: (0, 20), 10: (0, 5)},
    "Single-sized 20 mm": {40: (100, 100), 20: (85, 100), 10: (0, 20), 4.75: (0, 5)},
    "Single-sized 16 mm": {20: (100, 100), 16: (85, 100), 10: (0, 30), 4.75: (0, 5)},
    "Single-sized 12.5 mm": {16: (100, 100), 12.5: (85, 100), 10: (0, 45), 4.75: (0, 10)},
    "Single-sized 10 mm": {12.5: (100, 100), 10: (85, 100), 4.75: (0, 20), 2.36: (0, 5)},
    "Graded 40 mm": {80: (100, 100), 40: (90, 100), 20: (30, 70), 10: (10, 35), 4.75: (0, 5)},
    "Graded 20 mm": {40: (100, 100), 20: (90, 100), 10: (25, 55), 4.75: (0, 10)},
    "Graded 16 mm": {20: (100, 100), 16: (90, 100), 10: (30, 70), 4.75: (0, 10)},
    "Graded 12.5 mm": {20: (100, 100), 12.5: (90, 100), 10: (40, 85), 4.75: (0, 10)},
}

# IS 383:2016 Table 9 (cl. 6.3). Percent passing.
FINE_SIEVES = [10, 4.75, 2.36, 1.18, 0.6, 0.3, 0.15]
FINE_ZONES = {
    "Zone I": {10: (100, 100), 4.75: (90, 100), 2.36: (60, 95), 1.18: (30, 70), 0.6: (15, 34), 0.3: (5, 20), 0.15: (0, 10)},
    "Zone II": {10: (100, 100), 4.75: (90, 100), 2.36: (75, 100), 1.18: (55, 90), 0.6: (35, 59), 0.3: (8, 30), 0.15: (0, 10)},
    "Zone III": {10: (100, 100), 4.75: (90, 100), 2.36: (85, 100), 1.18: (75, 100), 0.6: (60, 79), 0.3: (12, 40), 0.15: (0, 10)},
    "Zone IV": {10: (100, 100), 4.75: (95, 100), 2.36: (95, 100), 1.18: (90, 100), 0.6: (80, 100), 0.3: (15, 50), 0.15: (0, 15)},
}
CRUSHED_SAND_150_MAX = 20  # Table 9 Note 1: crushed stone sand, 150 µm limit increased to 20 percent.

COARSE_SOURCES = ["Uncrushed", "Crushed", "Manufactured"]
FINE_SOURCES = ["Uncrushed (natural sand)", "Crushed stone sand", "Mixed sand", "Manufactured"]
USES = {"wearing": "Concrete for wearing surfaces", "other": "Other concrete"}


# ---------------------------------------------------------------- test sets

# IS 383:2016 Table 2, read from the BIS page image (archive.org gov.in.is.383.2016, page n4):
# columns 4 to 9 = fine uncrushed, fine crushed/mixed, fine manufactured, coarse uncrushed, coarse crushed,
# coarse manufactured. "—" in the table = no requirement, so the parameter is not added for that column.
TOTAL_NOTE = {
    "rows_i_v": "Table 2 row (vi): for this column the total includes rows (i) to (v).",
    "rows_i_ii": "Table 2 row (vi): for this column the total includes rows (i) and (ii) only.",
}

# Table 2 Note 3 (fine aggregate). The user chooses which case applies.
MICA_BASES = {
    "no_tests": ("No strength and durability tests are conducted", 1.00),
    "muscovite": ("Workability, strength, permeability and abrasion tests are conducted; muscovite mica", 3.00),
    "both": ("Workability, strength, permeability and abrasion tests are conducted; muscovite and biotite mica", 5.00),
}
MICA_NOTE = ("IS 383:2016 Table 2 Note 3: where no tests for strength and durability are conducted, mica may be limited "
             "to 1.00 %; where tests are conducted to ensure adequate workability, satisfactory strength, permeability and "
             "abrasion (for wearing surfaces), up to 3.00 % muscovite mica is permitted; with both muscovite and biotite "
             "mica, 5.00 % maximum. This is subject to total deleterious materials (including mica) of 8.00 % for "
             "uncrushed sand (col 4) and 5.00 % for crushed/mixed sand (col 5). IS 2386 (Part 2) has no mica method yet; "
             "the note says petrographic, density separation and wind blowing methods can normally be used.")


def _deleterious_coarse(source: str) -> list[Param]:
    total = 5.00 if source == "Uncrushed" else 2.00
    out = [
        Param("Material finer than 75 µm", "Deleterious materials", max=1.00, method="IS 2386 (Part 1)",
              clause="Table 2", frequency="Monthly", calc="finer75"),
        Param("Clay lumps", "Deleterious materials", max=1.00, method="IS 2386 (Part 2)", clause="Table 2",
              frequency="Monthly", calc="claylumps"),
        Param("Coal and lignite", "Deleterious materials", max=1.00, method="IS 2386 (Part 2)", clause="Table 2",
              frequency="Monthly", calc="lightweight"),
    ]
    if source in ("Uncrushed", "Manufactured"):      # col 7 and col 9: 3.00; col 8 (crushed): no requirement
        out.append(Param("Soft fragments", "Deleterious materials", max=3.00, method="IS 2386 (Part 2)",
                         clause="Table 2", frequency="Monthly"))
    out.append(Param("Total deleterious materials (excluding mica)", "Deleterious materials", max=total,
                     clause="Table 2", frequency="Quarterly",
                     note=TOTAL_NOTE["rows_i_ii" if source == "Manufactured" else "rows_i_v"]))
    return out


def _deleterious_fine(source: str, mica: str) -> list[Param]:
    if mica not in MICA_BASES:
        raise ValueError("Select which case of IS 383 Table 2 Note 3 applies to mica.")
    finer = {"Uncrushed (natural sand)": 3.00, "Crushed stone sand": 15.00, "Mixed sand": 12.00, "Manufactured": 10.00}[source]
    uncrushed = source == "Uncrushed (natural sand)"
    col5 = source in ("Crushed stone sand", "Mixed sand")
    total = 5.00 if uncrushed else 2.00
    out = [
        Param("Material finer than 75 µm", "Deleterious materials", max=finer, method="IS 2386 (Part 1)",
              clause="Table 2", frequency="Monthly", calc="finer75",
              note="Blended sand: each sand must meet Table 2, and uncrushed sand used for blending shall not have "
                   "material finer than 75 µm more than 3.00 % (Table 2 Note 1)." if source == "Mixed sand" else ""),
        Param("Clay lumps", "Deleterious materials", max=1.00, method="IS 2386 (Part 2)", clause="Table 2",
              frequency="Monthly", calc="claylumps"),
        Param("Coal and lignite", "Deleterious materials", max=1.00, method="IS 2386 (Part 2)", clause="Table 2",
              frequency="Monthly", calc="lightweight"),
    ]
    if not col5:                                      # col 4 and col 6: 1.00; col 5 (crushed/mixed): no requirement
        out.append(Param("Shale", "Deleterious materials", max=1.00, method="Petrography", clause="Table 2 Note 2",
                         frequency="Quarterly",
                         note="Table 2 Note 2: clay stones that are harder, platy and fissile are shales; their presence "
                              "and extent is determined by petrography at the time of selection and change of source."))
    out.append(Param("Total deleterious materials (excluding mica)", "Deleterious materials", max=total,
                     clause="Table 2", frequency="Quarterly",
                     note=TOTAL_NOTE["rows_i_v" if uncrushed else "rows_i_ii"]))
    label, limit = MICA_BASES[mica]
    out.append(Param("Mica", "Deleterious materials", max=limit, method="Petrographic, density separation or wind blowing",
                     clause="Table 2 Note 3", frequency="Quarterly", note=f"Case chosen: {label}. " + MICA_NOTE))
    if mica != "no_tests" and (uncrushed or col5):
        out.append(Param("Total deleterious materials (including mica)", "Deleterious materials",
                         max=8.00 if uncrushed else 5.00, clause="Table 2 Note 3", frequency="Quarterly"))
    out.append(Param("Organic impurities (colour test)", "Deleterious materials", unit="", method="IS 2386 (Part 2)",
                     clause="Table 2 Note 4", frequency="Six-monthly", value_type="passfail",
                     note="Fail = liquid darker than the standard solution. Such sand can still be accepted if mortar "
                          "strength at 7 and 28 days is at least 95 % of the reference (Table 2 Note 4)."))
    return out


def _physical(manufactured: bool, fine: bool) -> list[Param]:
    sg_min, sg_max = (2.1, 3.2) if manufactured else (None, None)
    wa_max = 5 if manufactured else None
    out = [
        Param("Specific gravity (oven-dry)", "Physical properties", unit="", min=sg_min, max=sg_max,
              method="IS 2386 (Part 3)", clause="Table 3" if manufactured else "", frequency="Monthly",
              calc="sg_pycnometer" if fine else "sg_basket",
              note="Table 3 limits apply to manufactured aggregates, for normal-weight concrete." if manufactured else
                   "IS 383:2016 sets no limit for natural aggregate; value is recorded for mix design."),
        Param("Apparent specific gravity", "Physical properties", unit="", method="IS 2386 (Part 3)",
              frequency="Monthly", calc="sg_pycnometer" if fine else "sg_basket"),
        Param("Water absorption", "Physical properties", max=wa_max, method="IS 2386 (Part 3)",
              clause="Table 3" if manufactured else "", frequency="Monthly",
              calc="sg_pycnometer" if fine else "sg_basket",
              note="Recycled concrete aggregate and recycled aggregate may go up to 10 % if pre-wetted before batching "
                   "(Table 3 Note 1)." if manufactured else "IS 383:2016 sets no limit for natural aggregate."),
        Param("Bulk density, loose", "Physical properties", unit="kg/L", method="IS 2386 (Part 3)",
              frequency="Monthly", calc="bulk_density"),
        Param("Bulk density, rodded", "Physical properties", unit="kg/L", method="IS 2386 (Part 3)",
              frequency="Monthly", calc="bulk_density"),
        Param("Voids (rodded)", "Physical properties", method="IS 2386 (Part 3)", frequency="Monthly", calc="voids"),
    ]
    if fine:
        out.append(Param("Bulking of sand", "Physical properties", method="IS 2386 (Part 3)", frequency="When required",
                         calc="bulking"))
    return out


def _soundness(fine: bool) -> list[Param]:
    na, mg = (10, 15) if fine else (12, 18)
    note = ("For concrete exposed to frost. Average loss after 5 cycles. IS 383:2016 cl. 5.5.1 leaves the limit to "
            "agreement between purchaser and supplier and gives this value as the guideline.")
    return [
        Param("Soundness, sodium sulphate (5 cycles)", "Soundness", max=na, method="IS 2386 (Part 5)",
              clause="5.5.1", frequency="Monthly", note=note),
        Param("Soundness, magnesium sulphate (5 cycles)", "Soundness", max=mg, method="IS 2386 (Part 5)",
              clause="5.5.1", frequency="Monthly", note=note),
    ]


def coarse_set(source: str, grading: str, use: str, m65: bool, frost: bool) -> list[Param]:
    if source not in COARSE_SOURCES or grading not in COARSE_GRADING or use not in USES:
        raise ValueError("Unknown option.")
    out = [Param(f"Passing {sieve_label(mm)} sieve", "Grading", min=lo, max=hi, method="IS 2386 (Part 1)",
                 clause=f"Table 7 ({grading})", calc="sieve", sieve_mm=float(mm))
           for mm, (lo, hi) in sorted(COARSE_GRADING[grading].items(), reverse=True)]
    out += _deleterious_coarse(source)
    out += [
        Param("Flakiness index", "Particle shape", method="IS 2386 (Part 1)", calc="shape"),
        Param("Elongation index (on non-flaky portion)", "Particle shape", method="IS 2386 (Part 1)", calc="shape"),
        Param("Combined flakiness and elongation index", "Particle shape", max=40, method="IS 2386 (Part 1)",
              clause="5.3", calc="shape",
              note="Sum of flakiness index and elongation index; elongation is measured on the non-flaky portion. "
                   "The engineer-in-charge may relax the limit (cl. 5.3)."),
    ]
    wearing = use == "wearing"
    crushing_max = 22 if m65 else (30 if wearing else None)
    impact_max = 22 if m65 else (30 if wearing else 45)
    out += [
        Param("Aggregate crushing value", "Mechanical properties", max=crushing_max, method="IS 2386 (Part 4)",
              clause="5.4.1" + (" note (M65 and above)" if m65 else ""), calc="crushing",
              note="" if crushing_max is not None else
              "For other concrete IS 383:2016 sets no maximum; where the crushing value exceeds 30 %, the ten per cent "
              "fines value is determined instead (cl. 5.4.1)."),
    ]
    if not wearing and not m65:
        out.append(Param("Ten per cent fines value", "Mechanical properties", unit="kN", min=50,
                         method="IS 2386 (Part 4)", clause="5.4.1", frequency="When required", calc="ten_fines",
                         note="Required where the aggregate crushing value exceeds 30 % (cl. 5.4.1)."))
    out += [
        Param("Aggregate impact value", "Mechanical properties", max=impact_max, method="IS 2386 (Part 4)",
              clause="5.4.2" + (" note (M65 and above)" if m65 else ""), calc="impact",
              note="Impact value may be determined as an alternative to the crushing value (cl. 5.4.2)."),
        Param("Los Angeles abrasion value", "Mechanical properties", max=30 if wearing else 50,
              method="IS 2386 (Part 4)", clause="5.4.3", calc="abrasion"),
    ]
    out += _physical(source == "Manufactured", fine=False)
    if frost:
        out += _soundness(fine=False)
    return out


def fine_set(source: str, zone: str, frost: bool, mica: str = "") -> list[Param]:
    if source not in FINE_SOURCES or zone not in FINE_ZONES:
        raise ValueError("Unknown option.")
    crushed = source == "Crushed stone sand"
    out = []
    for mm in FINE_SIEVES:
        lo, hi = FINE_ZONES[zone][mm]
        note = ""
        if mm == 0.15 and crushed:
            hi = max(hi, CRUSHED_SAND_150_MAX)
            note = "Crushed stone sand: 150 µm limit increased to 20 % (Table 9 Note 1)."
        out.append(Param(f"Passing {sieve_label(mm)} sieve", "Grading", min=lo, max=hi, method="IS 2386 (Part 1)",
                         clause=f"Table 9 ({zone})", calc="sieve", sieve_mm=float(mm), note=note))
    out.append(Param("Fineness modulus", "Grading", unit="", method="IS 2386 (Part 1) sieve analysis", calc="sieve",
                     note="Calculated from the sieve analysis. IS 383:2016 sets no limit; recorded for mix design."))
    out += _deleterious_fine(source, mica)
    out += _physical(source == "Manufactured", fine=True)
    if frost:
        out += _soundness(fine=True)
    return out


# ---------------------------------------------------------------- zone determination (Table 9, cl. 6.3)

def classify_zone(passing: dict[float, float], crushed: bool = False) -> list[dict]:
    """Return, for each zone, whether the grading falls within it under cl. 6.3.

    A grading outside a zone on a sieve is still within the zone if the excess is not more than 5 % on that sieve,
    with a cumulative total of not more than 10 %. The tolerance does not apply to the 600 µm sieve, to the coarse
    limit of Zone I, or to the finer limit of Zone IV.
    """
    out = []
    for zone, limits in FINE_ZONES.items():
        excess_total, ok, notes = 0.0, True, []
        for mm, (lo, hi) in limits.items():
            if mm == 0.15 and crushed:
                hi = max(hi, CRUSHED_SAND_150_MAX)
            v = passing.get(mm)
            if v is None:
                continue
            below, above = max(0.0, lo - v), max(0.0, v - hi)
            if not below and not above:
                continue
            excess = below or above
            no_tol = mm == 0.6 or (zone == "Zone I" and below) or (zone == "Zone IV" and above)
            label = sieve_label(mm)
            if no_tol or excess > 5:
                ok = False
                notes.append(f"{label}: {v:g} outside {lo:g}–{hi:g}" + (" (no tolerance)" if no_tol else ""))
            else:
                excess_total += excess
                notes.append(f"{label}: {v:g} outside {lo:g}–{hi:g} by {excess:g} (within 5 % tolerance)")
        if excess_total > 10:
            ok = False
            notes.append(f"cumulative excess {excess_total:g} > 10")
        out.append({"zone": zone, "within": ok, "notes": notes, "tolerance_used": excess_total})
    return out


# ---------------------------------------------------------------- worksheets (IS 2386 formulas)

@dataclass
class Calc:
    title: str
    method: str
    inputs: list[tuple[str, str]]          # (key, label)
    formulas: list[str]                     # shown to the user
    outputs: dict[str, str] = field(default_factory=dict)  # parameter-name fragment -> result key


CALCS = {
    "finer75": Calc("Material finer than 75 µm (washing)", "IS 2386 (Part 1) cl. 3.5",
                    [("B", "Original dry mass, g"), ("C", "Dry mass after washing, g")],
                    ["Finer than 75 µm (%) = (B − C) / B × 100"]),
    "claylumps": Calc("Clay lumps", "IS 2386 (Part 2) cl. 2.5",
                      [("W", "Mass of test sample, g"), ("R", "Mass after removing clay lumps, g")],
                      ["Clay lumps (%) = (W − R) / W × 100"]),
    "lightweight": Calc("Coal and lignite (light-weight pieces, heavy liquid SG 2.00)", "IS 2386 (Part 2) cl. 4.6",
                        [("W1", "Dry mass of pieces that float, g"),
                         ("W2", "Dry mass of sample tested (fine: coarser than 300 µm; coarse: coarser than 4.75 mm), g")],
                        ["Light-weight pieces (%) = W1 / W2 × 100"]),
    "crushing": Calc("Aggregate crushing value (12.5–10 mm fraction, 40 t load)", "IS 2386 (Part 4) cl. 2.5",
                     [("A", "Mass of surface-dry sample, g"), ("B", "Mass passing 2.36 mm sieve, g")],
                     ["Crushing value (%) = B / A × 100"]),
    "impact": Calc("Aggregate impact value (12.5–10 mm fraction, 15 blows)", "IS 2386 (Part 4) cl. 4.5",
                   [("A", "Mass of oven-dry sample, g"), ("B", "Mass passing 2.36 mm sieve, g")],
                   ["Impact value (%) = B / A × 100"]),
    "abrasion": Calc("Los Angeles abrasion value", "IS 2386 (Part 4) cl. 5.3.5",
                     [("A", "Original mass of sample, g"), ("B", "Mass retained on 1.70 mm sieve after test, g")],
                     ["Abrasion value (%) = (A − B) / A × 100"]),
    "ten_fines": Calc("Ten per cent fines value", "IS 2386 (Part 4) cl. 3.5",
                      [("x", "Load applied, kN"), ("y", "Mean percentage fines at that load (7.5–12.5 %), %")],
                      ["Load for 10 % fines = 14 x / (y + 4)"]),
    "shape": Calc("Flakiness and elongation index", "IS 2386 (Part 1) cl. 4, 5; IS 383:2016 cl. 5.3",
                  [("M", "Mass of sample gauged (retained on 6.3 mm), g"),
                   ("F", "Mass passing the thickness gauge (flaky), g"),
                   ("E", "Mass of non-flaky portion retained on the length gauge (elongated), g")],
                  ["Flakiness index (%) = F / M × 100",
                   "Elongation index (%) = E / (M − F) × 100   (non-flaky portion)",
                   "Combined index (%) = flakiness index + elongation index"]),
    "sg_basket": Calc("Specific gravity and water absorption, wire basket (aggregate larger than 10 mm)",
                      "IS 2386 (Part 3) cl. 2.2",
                      [("A1", "Basket + saturated sample in water, g"), ("A2", "Empty basket in water, g"),
                       ("B", "Saturated surface-dry sample in air, g"), ("C", "Oven-dry sample in air, g")],
                      ["A = A1 − A2 (saturated sample in water)", "Specific gravity = C / (B − A)",
                       "Apparent specific gravity = C / (C − A)", "Water absorption (%) = 100 (B − C) / C"]),
    "sg_pycnometer": Calc("Specific gravity and water absorption, pycnometer (aggregate smaller than 10 mm)",
                          "IS 2386 (Part 3) cl. 2.4",
                          [("A", "Saturated surface-dry sample, g"), ("B", "Pycnometer + sample + water, g"),
                           ("C", "Pycnometer + water, g"), ("D", "Oven-dry sample, g")],
                          ["Specific gravity = D / (A − (B − C))", "Apparent specific gravity = D / (D − (B − C))",
                           "Water absorption (%) = 100 (A − D) / D"]),
    "bulk_density": Calc("Bulk density", "IS 2386 (Part 3) cl. 3.4",
                         [("W", "Net mass of aggregate in the measure, kg"), ("V", "Capacity of the measure, litres")],
                         ["Bulk density (kg/L) = W / V"]),
    "voids": Calc("Percentage of voids", "IS 2386 (Part 3) cl. 3.5",
                  [("G", "Specific gravity"), ("Y", "Bulk density, kg/L")],
                  ["Voids (%) = (G − Y) / G × 100"]),
    "bulking": Calc("Bulking of sand (container method)", "IS 2386 (Part 3) cl. 4.3",
                    [("h", "Height of loose damp sand, mm"), ("h2", "Height after inundation, mm")],
                    ["Bulking (%) = (h / h2 − 1) × 100"]),
    # ---- cement worksheets (IS 4031, 1988/1999 texts, law.resource.org copies)
    "cube": Calc("Mortar cube compressive strength", "IS 4031 (Part 6):1988 cl. 8.1",
                 [("L1", "Cube 1: mean length of loaded face, mm"), ("B1", "Cube 1: mean width of loaded face, mm"),
                  ("P1", "Cube 1: maximum load, kN"),
                  ("L2", "Cube 2: mean length, mm"), ("B2", "Cube 2: mean width, mm"), ("P2", "Cube 2: maximum load, kN"),
                  ("L3", "Cube 3: mean length, mm"), ("B3", "Cube 3: mean width, mm"), ("P3", "Cube 3: maximum load, kN")],
                 ["Strength (MPa = N/mm²) = P × 1000 / (L × B)   for each cube",
                  "Cubes differing by more than 10 % from the average of all cubes are disregarded (cl. 8.1)",
                  "Result = average of the remaining cubes, to the nearest 0.5 MPa; fewer than 2 remaining = retest"]),
    "consistency": Calc("Standard consistency (Vicat plunger 5 to 7 mm from the bottom of the mould)",
                        "IS 4031 (Part 4):1988 cl. 5, 6.1",
                        [("W", "Mass of water in the paste that gave 5 to 7 mm, g"), ("C", "Mass of cement, g")],
                        ["Standard consistency P (%) = W / C × 100, to the first decimal place (cl. 6.1)"]),
    "setting": Calc("Initial and final setting time", "IS 4031 (Part 5):1988 cl. 5, 6.1",
                    [("Ti", "Time from adding water to initial set, min"),
                     ("Tf", "Time from adding water to final set, min"),
                     ("P", "Optional: standard consistency, %"), ("Mc", "Optional: mass of cement, g")],
                    ["Initial and final setting time are reported to the nearest five minutes (cl. 6.1)",
                     "Gauging water (g) = 0.85 × P / 100 × Mc   (paste at 0.85 times standard consistency water, cl. 5.1)"]),
    "blaine": Calc("Fineness by Blaine air permeability (porosity 0.500)", "IS 4031 (Part 2):1999 cl. 5.3.1, 5.7",
                   [("K", "Apparatus constant"), ("rho", "Density of cement, g/cm³"), ("T", "Test temperature, °C"),
                    ("t1", "Bed 1: time of flow, s"), ("t2", "Optional: bed 2: time of flow, s")],
                   ["At 27 ± 2 °C: S (cm²/g) = 521.08 × K × √t / ρ",
                    "At 20 ± 2 °C: S (cm²/g) = 524.2 × K × √t / ρ",
                    "S is the mean of the beds tested, reported to the nearest 10 cm²/g (cl. 5.7)",
                    "m²/kg = cm²/g ÷ 10"]),
}

# Fine sieves used for fineness modulus = sum of cumulative % retained on these sieves / 100.
FM_SIEVES = [80, 40, 20, 10, 4.75, 2.36, 1.18, 0.6, 0.3, 0.15]


def _r(v: float, nd: int = 2) -> float:
    return round(v + 0.0, nd)


def _nearest(v: float, step: float) -> float:
    """Round to the nearest multiple of step, halves upward (IS 2 rounding of a positive value)."""
    import math
    return math.floor(v / step + 0.5) * step


def run_calc(key: str, values: dict[str, float]) -> dict[str, float]:
    """Compute worksheet results. Raises ValueError with a readable message on bad input."""
    v = {k: float(x) for k, x in values.items() if x is not None}

    def need(*keys):
        missing = [k for k in keys if k not in v]
        if missing:
            raise ValueError("Enter " + ", ".join(missing) + ".")

    def nonzero(x, label):
        if x == 0:
            raise ValueError(f"{label} cannot be zero.")
        return x

    if key == "finer75":
        need("B", "C")
        return {"value": _r((v["B"] - v["C"]) / nonzero(v["B"], "B") * 100)}
    if key == "claylumps":
        need("W", "R")
        return {"value": _r((v["W"] - v["R"]) / nonzero(v["W"], "W") * 100)}
    if key == "lightweight":
        need("W1", "W2")
        return {"value": _r(v["W1"] / nonzero(v["W2"], "W2") * 100)}
    if key in ("crushing", "impact"):
        need("A", "B")
        return {"value": _r(v["B"] / nonzero(v["A"], "A") * 100, 1)}
    if key == "abrasion":
        need("A", "B")
        return {"value": _r((v["A"] - v["B"]) / nonzero(v["A"], "A") * 100, 1)}
    if key == "ten_fines":
        need("x", "y")
        return {"value": _r(14 * v["x"] / nonzero(v["y"] + 4, "y + 4"), 1)}
    if key == "shape":
        need("M", "F", "E")
        fi = v["F"] / nonzero(v["M"], "M") * 100
        ei = v["E"] / nonzero(v["M"] - v["F"], "M − F") * 100
        return {"flakiness": _r(fi, 1), "elongation": _r(ei, 1), "combined": _r(fi + ei, 1)}
    if key == "sg_basket":
        need("A1", "A2", "B", "C")
        a = v["A1"] - v["A2"]
        return {"sg": _r(v["C"] / nonzero(v["B"] - a, "B − A"), 3), "apparent": _r(v["C"] / nonzero(v["C"] - a, "C − A"), 3),
                "absorption": _r(100 * (v["B"] - v["C"]) / nonzero(v["C"], "C"))}
    if key == "sg_pycnometer":
        need("A", "B", "C", "D")
        disp = v["A"] - (v["B"] - v["C"])
        return {"sg": _r(v["D"] / nonzero(disp, "A − (B − C)"), 3),
                "apparent": _r(v["D"] / nonzero(v["D"] - (v["B"] - v["C"]), "D − (B − C)"), 3),
                "absorption": _r(100 * (v["A"] - v["D"]) / nonzero(v["D"], "D"))}
    if key == "bulk_density":
        need("W", "V")
        return {"value": _r(v["W"] / nonzero(v["V"], "V"), 3)}
    if key == "voids":
        need("G", "Y")
        return {"value": _r((v["G"] - v["Y"]) / nonzero(v["G"], "G") * 100, 1)}
    if key == "bulking":
        need("h", "h2")
        return {"value": _r((v["h"] / nonzero(v["h2"], "h2") - 1) * 100, 1)}
    if key == "cube":
        cubes = {}
        for i in (1, 2, 3):
            got = [k for k in (f"L{i}", f"B{i}", f"P{i}") if k in v]
            if not got:
                continue
            need(f"L{i}", f"B{i}", f"P{i}")
            cubes[i] = v[f"P{i}"] * 1000 / nonzero(v[f"L{i}"] * v[f"B{i}"], f"L{i} × B{i}")
        if len(cubes) < 2:
            raise ValueError("Enter at least two cubes.")
        avg = sum(cubes.values()) / len(cubes)
        kept = {i: x for i, x in cubes.items() if abs(x - avg) <= 0.10 * avg}
        out = {f"cube{i}": _r(x, 2) for i, x in cubes.items()}
        out["disregarded"] = ", ".join(f"cube {i}" for i in cubes if i not in kept) or "none"
        if len(kept) < 2:
            raise ValueError("Fewer than two cubes are within 10 % of the average: IS 4031 (Part 6) cl. 8.1 "
                             "requires a retest.")
        out["value"] = _nearest(sum(kept.values()) / len(kept), 0.5)
        return out
    if key == "consistency":
        need("W", "C")
        return {"value": _r(v["W"] / nonzero(v["C"], "C") * 100, 1)}
    if key == "setting":
        need("Ti", "Tf")
        if v["Tf"] < v["Ti"]:
            raise ValueError("Final setting time cannot be less than the initial setting time.")
        out = {"initial": _nearest(v["Ti"], 5), "final": _nearest(v["Tf"], 5)}
        if "P" in v and "Mc" in v:
            out["water_g"] = _r(0.85 * v["P"] / 100 * v["Mc"], 1)
        return out
    if key == "blaine":
        need("K", "rho", "T", "t1")
        if 25 <= v["T"] <= 29:
            const = 521.08
        elif 18 <= v["T"] <= 22:
            const = 524.2
        else:
            raise ValueError("Test temperature must be 27 ± 2 °C or 20 ± 2 °C for these formulas (IS 4031 Part 2 cl. 5.1).")
        rho = nonzero(v["rho"], "rho")
        times = [v[k] for k in ("t1", "t2") if k in v]
        if any(t <= 0 for t in times):
            raise ValueError("Time of flow must be more than zero.")
        each = [const * v["K"] * t ** 0.5 / rho for t in times]
        s_cm2g = _nearest(sum(each) / len(each), 10)
        out = {"cm2_per_g": s_cm2g, "value": _r(s_cm2g / 10, 1)}
        for i, x in enumerate(each, 1):
            out[f"bed{i}_cm2_per_g"] = _r(x, 0)
        return out
    raise ValueError("Unknown worksheet.")


def sieve_analysis(retained: dict[float, float], total: float | None = None) -> dict:
    """Masses retained on each sieve (g) -> cumulative % passing (nearest whole number, IS 2386 Pt 1 cl. 2.6)
    and fineness modulus. `total` defaults to the sum of retained masses plus the pan if given as key 0."""
    if not retained:
        raise ValueError("Enter the mass retained on at least one sieve.")
    if any(m < 0 for m in retained.values()):
        raise ValueError("Masses cannot be negative.")
    tot = total if total else sum(retained.values())
    if not tot:
        raise ValueError("Total mass cannot be zero.")
    sieves = sorted((s for s in retained if s > 0), reverse=True)
    cum, passing, cum_ret = 0.0, {}, {}
    for s in sieves:
        cum += retained[s]
        cum_ret[s] = cum / tot * 100
        passing[s] = round(100 - cum_ret[s])
    fm_sieves = [s for s in FM_SIEVES if s in cum_ret]
    fm = round(sum(cum_ret[s] for s in fm_sieves) / 100, 2) if fm_sieves else None
    return {"passing": passing, "cumulative_retained": {s: round(x, 1) for s, x in cum_ret.items()}, "fm": fm,
            "fm_sieves": fm_sieves, "total": tot}
