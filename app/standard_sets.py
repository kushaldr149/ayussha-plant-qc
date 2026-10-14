"""One registry for every standard test set that can be applied to a material (except IS 383 aggregates,
which have their own page with grading options)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import cement_library as cem
from . import is_library as lib
from . import scm_library as scm


@dataclass
class Field:
    name: str
    label: str
    kind: str = "select"          # select / number / frequency
    choices: list[str] = field(default_factory=list)
    required: bool = True
    hint: str = ""


@dataclass
class StandardSet:
    key: str
    label: str
    categories: tuple[str, ...]
    fields: list[Field]
    build: Callable[[dict], list]
    sources: list[tuple[str, str]]


def _freq(name: str, label: str) -> Field:
    return Field(name, label, "frequency", lib.FREQUENCIES,
                 hint="Not set by the standards; this is your plant's choice.")


PF = _freq("phys_freq", "How often your lab runs the physical tests")
CF = _freq("chem_freq", "How often your lab runs the chemical tests")
F1 = _freq("phys_freq", "How often your lab runs these tests")


def _num(opts: dict, name: str, label: str) -> float | None:
    raw = str(opts.get(name, "") or "").strip().replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{label} must be a number.") from None


def _cement(kind):
    def build(o):
        return cem.cement_set(kind, o["phys_freq"], o["chem_freq"],
                              _num(o, "declared", "Declared fly ash or slag") if kind in ("PPC", "PSC") else None)
    return build


SETS: dict[str, StandardSet] = {}


def _add(ts: StandardSet):
    SETS[ts.key] = ts


for k, kind in (("opc43", "OPC 43"), ("opc53", "OPC 53"), ("ppc", "PPC"), ("psc", "PSC")):
    extra = []
    if kind in ("PPC", "PSC"):
        extra = [Field("declared", f"Declared {'fly ash' if kind == 'PPC' else 'slag'} %", "number", required=False,
                       hint="Optional, from the manufacturer's certificate. "
                            + ("Fills the insoluble residue limits. Allowed 15–35 %." if kind == "PPC" else "Allowed 25–70 %."))]
    _add(StandardSet(k, cem.TYPES[kind], ("Cement",), [PF, CF] + extra, _cement(kind), cem.SOURCES))

_SCM_CATS = ("Supplementary cementitious material", "Coating material", "Ground cementitious material")
_add(StandardSet("ggbs", "GGBS · IS 16714:2018", _SCM_CATS, [PF, CF],
             lambda o: scm.ggbs_set(o["phys_freq"], o["chem_freq"]), scm.SOURCES[:1]))
_add(StandardSet("flyash", "Fly ash (pozzolana) · IS 3812 (Part 1):2013", _SCM_CATS,
             [Field("fa_type", "Type of fly ash", choices=scm.FLY_ASH_TYPES,
                    hint="IS 3812 (Part 1) cl. 3.9: siliceous fly ash has reactive calcium oxide less than 10 % by mass."),
              PF, CF],
             lambda o: scm.fly_ash_set(o["fa_type"], o["phys_freq"], o["chem_freq"]), scm.SOURCES[1:2]))
_add(StandardSet("silicafume", "Silica fume (microsilica) · IS 15388:2003", _SCM_CATS, [PF, CF],
             lambda o: scm.silica_fume_set(o["phys_freq"], o["chem_freq"]), scm.SOURCES[2:3]))
_add(StandardSet("admixture", "Concrete admixture, uniformity tests · IS 9103:1999", ("Admixture",),
             [Field("ad_type", "Type of admixture (IS 9103 cl. 3)", choices=scm.ADMIXTURE_TYPES), F1,
              Field("dmc", "Stated dry material content, %", "number", required=False,
                    hint="From the manufacturer's data sheet. Fills the 0.95T–1.05T limits."),
              Field("ash", "Stated ash content, %", "number", required=False),
              Field("rd", "Stated relative density", "number", required=False),
              Field("chloride", "Stated chloride ion content, %", "number", required=False)],
             lambda o: scm.admixture_set(o["ad_type"], o["phys_freq"], _num(o, "dmc", "Dry material content"),
                                         _num(o, "ash", "Ash content"), _num(o, "rd", "Relative density"),
                                         _num(o, "chloride", "Chloride ion content")), scm.SOURCES[3:4]))
_add(StandardSet("synfibre", "Synthetic micro fibres (PP, polyester, nylon) · IS 16481:2022", ("Fibre",),
             [Field("fibre_type", "Fibre type", choices=scm.FIBRE_TYPES),
              Field("fibre_class", "Class (polypropylene and polyester)", choices=scm.FIBRE_CLASSES, required=False,
                    hint="Sets the minimum tensile strength: Class I 180, Class II 300, Class III 500 MPa (Table 1)."),
              F1],
             lambda o: scm.synthetic_fibre_set(o["fibre_type"], o.get("fibre_class", ""), o["phys_freq"]),
             scm.SOURCES[4:5]))


def sets_for(category: str) -> list[StandardSet]:
    return [s for s in SETS.values() if category in s.categories]


def build(key: str, opts) -> list:
    ts = SETS.get(key)
    if ts is None:
        raise ValueError("Select a test set.")
    clean = {}
    for f in ts.fields:
        v = str(opts.get(f.name, "") or "").strip()
        if f.kind in ("select", "frequency") and v and v not in f.choices:
            raise ValueError(f"{f.label}: select one of the options.")
        if f.required and not v:
            raise ValueError(f"{f.label}: select or enter a value.")
        clean[f.name] = v
    return ts.build(clean)
