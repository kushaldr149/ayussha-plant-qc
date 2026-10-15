"""Test sets for cement: OPC 43 and OPC 53 (IS 269:2015), PPC fly ash based (IS 1489 Part 1:2015), PSC (IS 455:2015).

Sources read for this module (October 2026):
  * IS 1489 (Part 1):2015, Fourth Revision, and its Amendment No. 1 (July 2018): Internet Archive text
    (archive.org/details/gov.in.is.1489.1.2015). The autoclave value, garbled in the OCR text, was read from the
    page image of the same PDF (0.8).
  * IS 455:2015, Fifth Revision, with Amendment No. 1 (June 2018) and Amendment No. 2 (May 2023): Internet Archive
    text (archive.org/details/gov.in.is.455.2015). Neither amendment changes a limit used here.
  * IS 269:2015 (Sixth Revision): the BIS text was not available. Limits are taken from the Indian Railways
    CAMTECH pamphlet "Requirements of Ordinary Portland Cement as per IS 269-2015" (CAMTECH/C/2022/OPC/1.0,
    February 2022), and checked against the "requirement as per IS 269:2015" columns of JSW Cement test
    certificates for OPC 43 and OPC 53. All three agree on every value used here.

Rules followed:
  * Only limits found in those sources are filled in. Test frequencies are NOT from these standards; the user
    chooses them when applying a set.
"""
from __future__ import annotations

from .is_library import Param

TYPES = {
    "OPC 43": "OPC 43 grade · IS 269:2015",
    "OPC 53": "OPC 53 grade · IS 269:2015",
    "PPC": "Portland pozzolana cement, fly ash based · IS 1489 (Part 1):2015",
    "PSC": "Portland slag cement · IS 455:2015",
}
STANDARD_OF = {"OPC 43": "IS 269:2015", "OPC 53": "IS 269:2015", "PPC": "IS 1489 (Part 1):2015", "PSC": "IS 455:2015"}

GROUPS = ["Physical requirements", "Chemical requirements", "Composition"]

SOURCES = [
    ("IS 1489 (Part 1):2015 with Amendment 1 (Internet Archive)", "https://archive.org/details/gov.in.is.1489.1.2015"),
    ("IS 455:2015 with Amendments 1 and 2 (Internet Archive)", "https://archive.org/details/gov.in.is.455.2015"),
    ("Requirements of OPC as per IS 269-2015, Indian Railways CAMTECH pamphlet (used for IS 269:2015)",
     "https://starcement.co.in/pdf/Pamphlet%20on%20Requirements%20of%20Ordinary%20Portland%20Cement%20as%20per%20IS%20269-2015.pdf"),
    ("JSW Cement test certificate, OPC 43, IS 269:2015 requirements (cross-check)", "https://www.jswcement.in/pdf/Nandyal-OPC43-W.29.pdf"),
    ("JSW Cement test certificate, OPC 53, IS 269:2015 requirements (cross-check)", "https://www.jswcement.in/pdf/Nandyal-OPC53-W.29.pdf"),
]

# (fineness min, LC max, autoclave max, IST min, FST max, 3 d min, 7 d min, 28 d min, 28 d max)
_PHYSICAL = {
    "OPC 43": (225, 10, 0.8, 30, 600, 23, 33, 43, 58),
    "OPC 53": (225, 10, 0.8, 30, 600, 27, 37, 53, None),
    "PPC": (300, 10, 0.8, 30, 600, 16, 22, 33, None),
    "PSC": (225, 10, 0.8, 30, 600, 16, 22, 33, None),
}

_ALKALI_NOTE = ("No limit. Where aggregates are reactive, cement with alkali content below 0.6 % (as Na₂O + 0.658 K₂O) "
                "is recommended (note under the chemical requirements table).")


def cement_set(kind: str, physical_freq: str, chemical_freq: str, declared_pct: float | None = None) -> list[Param]:
    """Parameters for one cement type. declared_pct = declared fly ash % (PPC) or slag % (PSC), optional."""
    if kind not in TYPES:
        raise ValueError("Unknown cement type.")
    std = STANDARD_OF[kind]
    blended = kind in ("PPC", "PSC")
    phys_ref, chem_ref = ("Table 2", "Table 1") if blended else ("physical requirements", "chemical requirements")
    fin, lc, ac, ist, fst, s3, s7, s28, s28max = _PHYSICAL[kind]
    pf, cf = physical_freq, chemical_freq

    def P(name, unit, lo, hi, method, clause, group="Physical requirements", freq=None, note="", calc=""):
        return Param(name, group, unit=unit, min=lo, max=hi, method=method, clause=clause, frequency=freq or pf,
                     note=note, standard=std, calc=calc)

    soundness_note = ("If the cement fails, retest after aeration (spread 75 mm deep, 50–80 % RH, 7 days); "
                      "aerated cement may expand not more than 5 mm (Le Chatelier) and 0.6 % (autoclave).")
    out = [
        P("Fineness (Blaine specific surface)", "m²/kg", fin, None, "IS 4031 (Part 2)", phys_ref, calc="blaine"),
        P("Standard consistency", "%", None, None, "IS 4031 (Part 4)", "", calc="consistency",
          note=f"No limit in {std}. The value sets the water for the setting time and soundness tests."),
        P("Soundness, Le Chatelier expansion", "mm", None, lc, "IS 4031 (Part 3)", phys_ref, note=soundness_note),
        P("Soundness, autoclave expansion", "%", None, ac, "IS 4031 (Part 3)", phys_ref, note=soundness_note),
        P("Initial setting time", "min", ist, None, "IS 4031 (Part 5)", phys_ref, calc="setting"),
        P("Final setting time", "min", None, fst, "IS 4031 (Part 5)", phys_ref, calc="setting"),
        P("Compressive strength, 3 days (72 ± 1 h)", "MPa", s3, None, "IS 4031 (Part 6)", phys_ref, calc="cube"),
        P("Compressive strength, 7 days (168 ± 2 h)", "MPa", s7, None, "IS 4031 (Part 6)", phys_ref, calc="cube"),
        P("Compressive strength, 28 days (672 ± 4 h)", "MPa", s28, s28max, "IS 4031 (Part 6)", phys_ref, calc="cube",
          note="The cement shall show a progressive increase in strength from the 3-day value." if blended else ""),
    ]
    if kind == "PPC":
        out.append(P("Drying shrinkage", "%", None, 0.15, "IS 4031 (Part 10)", phys_ref))

    def C(name, unit, lo, hi, note=""):
        return P(name, unit, lo, hi, "IS 4032", chem_ref, group="Chemical requirements", freq=cf, note=note)

    chloride_note = "0.05 % maximum for prestressed structures."
    if kind in ("OPC 43", "OPC 53"):
        out += [
            C("Lime saturation factor", "", 0.66 if kind == "OPC 43" else 0.80, 1.02,
              note="Ratio of lime to silica, alumina and iron oxide, calculated by the formula in IS 269."),
            C("Alumina to iron oxide ratio", "", 0.66, None),
            C("Insoluble residue", "%", None, 5.0),
            C("Magnesia (MgO)", "%", None, 6.0),
            C("Total sulphur as SO₃", "%", None, 3.5),
            C("Loss on ignition", "%", None, 5.0 if kind == "OPC 43" else 4.0),
            C("Chloride content", "%", None, 0.1, chloride_note),
            C("Alkali content (Na₂O + 0.658 K₂O)", "%", None, None, _ALKALI_NOTE),
        ]
    elif kind == "PPC":
        x = declared_pct
        if x is not None and not (15 <= x <= 35):
            raise ValueError("Declared fly ash must be between 15 and 35 % (IS 1489 Part 1 cl. 5).")
        ir_max = round(x + 4.0 * (100 - x) / 100, 2) if x is not None else None
        ir_min = round(0.6 * x, 2) if x is not None else None
        ir_note = ("Limits depend on the declared fly ash x: maximum x + 4.0(100 − x)/100, minimum 0.6x (Table 1). "
                   + (f"Calculated for x = {x:g} %; apply the set again if the declared fly ash changes." if x is not None
                      else "Enter the declared fly ash when applying the set to fill these limits."))
        out += [
            C("Insoluble residue", "%", ir_min, ir_max, ir_note),
            C("Magnesia (MgO)", "%", None, 6.0),
            C("Total sulphur as SO₃", "%", None, 3.5),
            C("Loss on ignition", "%", None, 5.0),
            C("Chloride content", "%", None, 0.1, chloride_note),
            C("Alkali content (Na₂O + 0.658 K₂O)", "%", None, None,
              _ALKALI_NOTE + " Amendment 1 (2018): for cement with at least 30 % fly ash, 0.9 % maximum is recommended."),
            P("Fly ash content (declared)", "%", 15, 35, "Manufacturer's declaration", "cl. 5", group="Composition",
              freq="Every lot", note="Homogeneity within ±3 % of the declared fly ash in the same consignment (cl. 5)."),
        ]
    else:  # PSC
        if declared_pct is not None and not (25 <= declared_pct <= 70):
            raise ValueError("Declared slag must be between 25 and 70 % (IS 455 cl. 5).")
        out += [
            C("Insoluble residue", "%", None, 4.0),
            C("Magnesia (MgO)", "%", None, 10.0),
            C("Total sulphur as SO₃", "%", None, 3.5),
            C("Sulphide sulphur (S)", "%", None, 1.5),
            C("Loss on ignition", "%", None, 5.0),
            C("Chloride content", "%", None, 0.1, chloride_note),
            C("Alkali content (Na₂O + 0.658 K₂O)", "%", None, None,
              _ALKALI_NOTE + " Amendment 1 (2018): for cement with at least 50 % slag, 0.9 % maximum is recommended."),
            P("Granulated slag content (declared)", "%", 25, 70, "Manufacturer's declaration", "cl. 5",
              group="Composition", freq="Every lot",
              note="Homogeneity within ±3 % of the declared slag in the same consignment (cl. 5)."),
        ]
    return out
