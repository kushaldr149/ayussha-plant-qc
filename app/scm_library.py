"""Test sets for GGBS, fly ash, silica fume (microsilica), concrete admixtures and synthetic micro fibres.

Sources read (October 2026), all Internet Archive copies of the BIS texts:
  * IS 16714:2018 GGBS, with Amendment No. 1 (December 2019). Table 1 values read from the page image.
  * IS 3812 (Part 1):2013 Pulverized fuel ash for use as pozzolana. No amendment file was present in that copy.
  * IS 15388:2003 Silica fume, with Amendment No. 1 (April 2017).
  * IS 9103:1999 Concrete admixtures, with Amendments No. 1 (January 2003) and No. 2 (August 2007):
    Table 2 uniformity tests only (per batch). Table 1A/1B performance tests compare concrete with and
    without the admixture and are acceptance (type) tests; they are not part of this set.
  * IS 16481:2022 Synthetic micro fibres for use in cement based matrix, with Amendment No. 1 (October 2022).
    Table 1 values read from the page image.
No IS for steel fibres or for Alccofine was found in those sources; no set is offered for them.
"""
from __future__ import annotations

from .is_library import Param

SOURCES = [
    ("IS 16714:2018 GGBS with Amendment 1 (Internet Archive)", "https://archive.org/details/gov.in.is.16714.2018"),
    ("IS 3812 (Part 1):2013 Fly ash (Internet Archive)", "https://archive.org/details/gov.in.is.3812.1.2013"),
    ("IS 15388:2003 Silica fume with Amendment 1 (Internet Archive)", "https://archive.org/details/gov.in.is.15388.2003"),
    ("IS 9103:1999 Concrete admixtures with Amendments 1 and 2 (Internet Archive)", "https://archive.org/details/gov.in.is.9103.1999"),
    ("IS 16481:2022 Synthetic micro fibres with Amendment 1 (Internet Archive)", "https://archive.org/details/gov.in.is.16481.2022"),
]

FLY_ASH_TYPES = ["Siliceous", "Calcareous"]
ADMIXTURE_TYPES = ["Accelerating", "Retarding", "Water reducing", "Air-entraining", "Superplasticizing, normal",
                   "Superplasticizing, retarding"]
FIBRE_TYPES = ["Polypropylene", "Polyester", "Nylon 6"]
FIBRE_CLASSES = ["Class I", "Class II", "Class III"]

PHYS, CHEM = "Physical requirements", "Chemical requirements"


def _p(std, name, group, unit, lo, hi, method, clause, freq, note="", value_type="number"):
    return Param(name, group, unit=unit, min=lo, max=hi, method=method, clause=clause, frequency=freq, note=note,
                 standard=std, value_type=value_type)


def ggbs_set(phys_freq: str, chem_freq: str) -> list[Param]:
    s = "IS 16714:2018"
    c = lambda n, u, lo, hi, note="", clause="Table 1", method="IS 4032": _p(s, n, CHEM, u, lo, hi, method, clause, chem_freq, note)  # noqa: E731
    either = "Amendment 1 (2019): GGBS shall satisfy any one of the two ratio requirements (viii) and (ix)."
    return [
        _p(s, "Fineness (Blaine specific surface)", PHYS, "m²/kg", 320, None, "IS 4031 (Part 2)", "Table 2", phys_freq),
        _p(s, "Slag activity index, 7 days", PHYS, "%", 60, None, "IS 4031 (Part 6)", "Table 2", phys_freq,
           "Blend of 50 % GGBS and 50 % control OPC 43 (IS 269, total alkalies 0.6–0.9 %), as percent of the control "
           "OPC mortar cube strength (Table 2 Note 2)."),
        _p(s, "Slag activity index, 28 days", PHYS, "%", 75, None, "IS 4031 (Part 6)", "Table 2", phys_freq,
           "As percent of the control OPC 43 mortar cube strength (Table 2 Note 2)."),
        c("Manganese oxide (MnO)", "%", None, 5.5),
        c("Magnesium oxide (MgO)", "%", None, 17.0),
        c("Sulphide sulphur (S)", "%", None, 2.0),
        c("Sulphate (as SO₃)", "%", None, 3.0),
        c("Insoluble residue", "%", None, 3.0),
        c("Chloride content", "%", None, 0.1),
        c("Loss on ignition", "%", None, 3.0),
        c("(CaO + MgO + 1/3 Al₂O₃) / (SiO₂ + 2/3 Al₂O₃)", "", 1.0, None, either),
        c("(CaO + MgO + Al₂O₃) / SiO₂", "", 1.0, None, either),
        c("(CaO + CaS + 1/2 MgO + Al₂O₃) / (SiO₂ + MnO)", "", 1.5, None,
          "For granulated slag with more than 2.5 % MnO. CaS = 2.25 × sulphide sulphur (Amendment 1)."),
        c("Moisture content", "%", None, 1.0, clause="cl. 5.2", method="Annex B"),
        c("Glass content", "%", 85, None, clause="cl. 5.3", method="Optical microscope, Annex C"),
    ]


def fly_ash_set(kind: str, phys_freq: str, chem_freq: str) -> list[Param]:
    if kind not in FLY_ASH_TYPES:
        raise ValueError("Select siliceous or calcareous fly ash.")
    s = "IS 3812 (Part 1):2013"
    sil = kind == "Siliceous"
    c = lambda n, u, lo, hi, method="IS 1727", note="": _p(s, n, CHEM, u, lo, hi, method, "Table 1", chem_freq, note)  # noqa: E731
    uniform = ("Uniformity (cl. 7.2): not to vary more than 15 % from the average of the 10 preceding samples "
               "(or all preceding samples if fewer than 10).")
    return [
        _p(s, "Fineness (Blaine specific surface)", PHYS, "m²/kg", 320, None, "IS 1727", "Table 2", phys_freq,
           uniform + " Cl. 5.1: fly ash coarser than Table 2 shall not be beneficiated by grinding to improve its "
           "fineness for use under this standard."),
        _p(s, "Retained on 45 µm sieve (wet sieving)", PHYS, "%", None, 34, "IS 1727", "Table 2", phys_freq,
           "Optional test. " + uniform),
        _p(s, "Lime reactivity (average compressive strength)", PHYS, "N/mm²", 4.5, None, "IS 1727", "Table 2",
           phys_freq, uniform),
        _p(s, "Compressive strength at 28 days, percent of plain cement mortar", PHYS, "%", 80, None, "IS 1727",
           "Table 2", phys_freq),
        _p(s, "Soundness, autoclave expansion", PHYS, "%", None, 0.8, "IS 1727", "Table 2", phys_freq),
        c("SiO₂ + Al₂O₃ + Fe₂O₃", "%", 70 if sil else 50, None),
        c("Silicon dioxide (SiO₂)", "%", 35 if sil else 25, None),
        c("Reactive silica", "%", 20, None, "Annex B",
          "The test may be carried out if agreed between the supplier and the purchaser (Table 1 footnote)."),
        c("Magnesium oxide (MgO)", "%", None, 5.0),
        c("Total sulphur as SO₃", "%", None, 3.0),
        c("Available alkalis as Na₂O", "%", None, 1.5, "Annex C"),
        c("Total chlorides", "%", None, 0.05, "IS 4032"),
        c("Loss on ignition", "%", None, 5.0),
        _p(s, "Moisture content (dry supply)", CHEM, "%", None, 2.0, "Annex D", "cl. 6.2", chem_freq,
           "Applies when fly ash is supplied dry."),
    ]


def silica_fume_set(phys_freq: str, chem_freq: str) -> list[Param]:
    s = "IS 15388:2003"
    either = "Table 2 Note 1: either the specific surface test, or the 45 µm oversize tests, may be adopted."
    return [
        _p(s, "Specific surface", PHYS, "m²/g", 15, None, "Annex B", "Table 2", phys_freq, either),
        _p(s, "Oversize retained on 45 µm sieve", PHYS, "%", None, 10, "IS 1727", "Table 2", phys_freq, either),
        _p(s, "Oversize on 45 µm, variation from average", PHYS, "%", None, 5, "IS 1727", "Table 2", phys_freq,
           "Average of the ten preceding tests, or all preceding tests if fewer than ten (Table 2 Note 2)."),
        _p(s, "Compressive strength at 7 days, percent of control", PHYS, "%", 85.0, None, "IS 1727", "Table 2",
           phys_freq, "Factor N taken as one in the IS 1727 method (Table 2 Note 3)."),
        _p(s, "Silicon dioxide (SiO₂)", CHEM, "%", 85.0, None, "IS 1727", "Table 1", chem_freq),
        _p(s, "Moisture content", CHEM, "%", None, 3.0, "Oven dry at 105–110 °C", "Table 1", chem_freq),
        _p(s, "Loss on ignition", CHEM, "%", None, 4.0, "IS 1727", "Table 1", chem_freq),
        _p(s, "Alkalies as Na₂O", CHEM, "%", None, 1.5, "Annex A (Amendment 1)", "Table 1", chem_freq,
           "Applies when the silica fume is used in concrete with reactive aggregate (Table 1 Note 2)."),
    ]


def admixture_set(kind: str, freq: str, dmc: float | None, ash: float | None, rd: float | None,
                  chloride: float | None) -> list[Param]:
    """IS 9103 Table 2 uniformity tests. Limits are built from the manufacturer's stated values."""
    if kind not in ADMIXTURE_TYPES:
        raise ValueError("Select the admixture type.")
    s = "IS 9103:1999"
    stated = "Enter the manufacturer's stated value when applying the set to fill this limit."

    def band(t, lo_f, hi_f):
        return (round(t * lo_f, 3), round(t * hi_f, 3)) if t is not None else (None, None)

    d_lo, d_hi = band(dmc, 0.95, 1.05)
    a_lo, a_hi = band(ash, 0.95, 1.05)
    r_lo, r_hi = (round(rd - 0.02, 3), round(rd + 0.02, 3)) if rd is not None else (None, None)
    if chloride is not None:
        tol = max(0.1 * chloride, 0.2)
        c_lo, c_hi = round(max(chloride - tol, 0), 3), round(chloride + tol, 3)
    else:
        c_lo = c_hi = None
    ash_note = "0.95T ≤ AC ≤ 1.05T, T = stated value (Amendment 2). "
    if kind == "Accelerating":
        ash_note += "Not applicable to an accelerating admixture containing more than 1 % chloride (Table 2 Note). "
    return [
        _p(s, "Dry material content", "Uniformity", "%", d_lo, d_hi, "Annex E", "Table 2", freq,
           "0.95T ≤ DMC ≤ 1.05T, T = stated value (Amendment 2). " + ("" if dmc is not None else stated)),
        _p(s, "Ash content", "Uniformity", "%", a_lo, a_hi, "Annex E", "Table 2", freq,
           ash_note + ("" if ash is not None else stated)),
        _p(s, "Relative density", "Uniformity", "", r_lo, r_hi, "Annex E", "Table 2", freq,
           "Within 0.02 of the stated value. " + ("" if rd is not None else stated)),
        _p(s, "Chloride ion content", "Uniformity", "%", c_lo, c_hi, "Annex E", "Table 2", freq,
           "Within 10 % of the stated value or within 0.2 %, whichever is greater. " + ("" if chloride is not None else stated)),
        _p(s, "pH", "Uniformity", "", 6, None, "Annex E", "Table 2", freq, "6 minimum (Amendment 2)."),
    ]


def synthetic_fibre_set(kind: str, cls: str, freq: str) -> list[Param]:
    if kind not in FIBRE_TYPES:
        raise ValueError("Select the fibre type.")
    if kind != "Nylon 6" and cls not in FIBRE_CLASSES:
        raise ValueError("Select the fibre class.")
    s = "IS 16481:2022"
    tensile = {"Class I": (180, None), "Class II": (300, None), "Class III": (500, None)}.get(cls, (None, None))
    if kind == "Nylon 6":
        tensile = (460, 800)
    sg = {"Polypropylene": (0.90, 0.91), "Polyester": (1.34, 1.39), "Nylon 6": (1.14, 1.20)}[kind]
    melt = {"Polypropylene": 160, "Polyester": 240, "Nylon 6": 180}[kind]
    phys = lambda n, u, lo, hi, method, clause, note="": _p(s, n, PHYS, u, lo, hi, method, clause, freq, note)  # noqa: E731
    out = [
        phys("Tensile strength", "MPa", *tensile, "IS 235", "Table 1"),
        phys("Specific gravity", "", *sg, "Annex G (Amendment 1)", "Table 1"),
        phys("Ultimate elongation", "%", 15, None, "IS 235", "Table 1"),
        phys("Melting temperature", "°C", melt, None, "Annex H", "Table 1",
             "240 °C for polyester per Amendment 1 (2022)." if kind == "Polyester" else ""),
    ]
    if kind == "Polypropylene":
        out.append(phys("Glass transition temperature", "°C", None, -10, "Annex H", "Table 1",
                        "Table 1 gives < −10 °C for polypropylene."))
    else:
        out.append(phys("Glass transition temperature", "°C", 60 if kind == "Polyester" else 50, None, "Annex H",
                        "Table 1", "60 °C for polyester per Amendment 1 (2022)." if kind == "Polyester" else ""))
    out += [
        _p(s, "Equivalent fibre diameter", "Application requirements", "µm", 7, 100, "Annex J", "Table 2", freq),
        _p(s, "Length", "Application requirements", "mm", 5, 25, "IS 10014 (Part 1)", "Table 2", freq,
           "Cl. 4.3 states cut length 6 mm to 25 mm; longer fibres are permitted if required by the customer."),
        _p(s, "Aspect ratio", "Application requirements", "", 100, 1000, "Annex K", "Table 2", freq),
        _p(s, "Resistance to alkalis, breaking strength retained", "Durability", "%", 90, None, "Annex D", "cl. 4.4", freq),
        _p(s, "Resistance to acids, breaking strength retained", "Durability", "%", 90, None, "Annex E", "cl. 4.5", freq),
        _p(s, "Resistance to ageing, tensile strength retained", "Durability", "%", 90, None, "IS 7016 (Part 8)", "cl. 4.6", freq),
        _p(s, "Resistance to UV light, tensile strength retained", "Durability", "%", 90, None, "Annex F", "cl. 4.7", freq),
        _p(s, "Drying shrinkage gain (concrete)", "Functional requirements", "%", 30, None, "IS 1199", "Table 3", freq,
           "Gain percent of the fibre-reinforced matrix over the control, calculated by the formula in Table 3 Note 1. Type test on the manufacturer's declared dosage."),
        _p(s, "Virgin fibre and polymer content certificate", "Certificates", "", None, None,
           "Manufacturer's test certificate for every lot", "cl. 4.3.1", "Every lot",
           "Virgin fibre only, no recycled material; polymer content at least 97 %, additives not more than 3 %.",
           value_type="passfail"),
    ]
    return out
