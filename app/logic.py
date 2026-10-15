"""Pure QC and production rules. No database or web code here, so it is easy to test."""
from __future__ import annotations

from collections.abc import Iterable


def parse_number(value) -> float | None:
    """Return a float from form input, or None when empty. Raises ValueError on bad input."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text == "":
        return None
    number = float(text)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("not a finite number")
    return number


def evaluate(value: float | None, min_value: float | None, max_value: float | None, periodic: bool = False) -> str:
    """Status of one test value against its limits: pass, fail, missing, skipped or nolimit.

    A periodic test (monthly, quarterly...) left empty is "skipped": it was not due, so it does not make
    the lot incomplete.
    """
    if value is None:
        return "skipped" if periodic else "missing"
    if min_value is None and max_value is None:
        return "nolimit"
    if min_value is not None and value < min_value:
        return "fail"
    if max_value is not None and value > max_value:
        return "fail"
    return "pass"


def overall_status(statuses: Iterable[str]) -> str:
    """Overall result of a test: fail if any value is out of limit, incomplete if any is missing."""
    statuses = [s for s in statuses if s != "skipped"]
    if not statuses:
        return "incomplete"
    if "fail" in statuses:
        return "fail"
    if "missing" in statuses:
        return "incomplete"
    return "pass"


def deviation_pct(planned: float | None, actual: float | None) -> float | None:
    """Deviation of actual from planned, as a percentage of planned."""
    if planned is None or actual is None or planned == 0:
        return None
    return (actual - planned) / planned * 100.0


def production_status(deviations: Iterable[float | None], tolerance_pct: float | None) -> tuple[str, float | None]:
    """Return (status, largest absolute deviation).

    status is ok, over, notol (tolerance not set) or nodata (no planned values to compare).
    """
    devs = [abs(d) for d in deviations if d is not None]
    if not devs:
        return "nodata", None
    largest = max(devs)
    if tolerance_pct is None:
        return "notol", largest
    return ("over" if largest > tolerance_pct else "ok"), largest


def item_status(pairs: Iterable[tuple[float | None, float | None]]) -> tuple[str, float | None]:
    """(deviation %, tolerance %) per line -> (status, largest absolute deviation).

    over: a line is outside its own tolerance. notol: a compared line has no tolerance set (and none is over).
    nodata: no planned values to compare. ok: every compared line is within its tolerance."""
    pairs = [(abs(d), t) for d, t in pairs if d is not None]
    if not pairs:
        return "nodata", None
    largest = max(d for d, _ in pairs)
    if any(t is not None and d > t for d, t in pairs):
        return "over", largest
    if any(t is None for _, t in pairs):
        return "notol", largest
    return "ok", largest


def single_tolerance(tols: Iterable[float | None]) -> float | None:
    """The tolerance shared by all lines, or None when lines differ or none is set."""
    vals = set(tols)
    return vals.pop() if len(vals) == 1 else None


def accept_needs_remark(overall: str, decision: str, remarks: str) -> bool:
    """A lot with out-of-limit results can only be accepted with a written remark."""
    return overall == "fail" and decision == "Accepted" and not (remarks or "").strip()


def limit_text(min_value: float | None, max_value: float | None, unit: str = "") -> str:
    u = f" {unit}" if unit else ""
    fmt = lambda n: f"{n:g}"  # noqa: E731
    if min_value is not None and max_value is not None:
        return f"{fmt(min_value)} – {fmt(max_value)}{u}"
    if min_value is not None:
        return f"≥ {fmt(min_value)}{u}"
    if max_value is not None:
        return f"≤ {fmt(max_value)}{u}"
    return "No limit set"


STATUS_LABELS = {
    "pass": "Within limits",
    "fail": "Out of limit",
    "incomplete": "Incomplete",
    "missing": "Not entered",
    "nolimit": "No limit set",
    "skipped": "Not tested (periodic)",
}


def limit_display(min_value, max_value, unit: str = "", value_type: str | None = "number") -> str:
    if value_type == "passfail":
        return "Pass required"
    return limit_text(min_value, max_value, unit)


def value_display(value, unit: str = "", value_type: str | None = "number") -> str:
    if value is None:
        return "—"
    if value_type == "passfail":
        return "Pass" if value >= 1 else "Fail"
    text = f"{value:,.4f}".rstrip("0").rstrip(".")
    return f"{text} {unit}".strip()

PRODUCTION_LABELS = {
    "ok": "Within tolerance",
    "over": "Over tolerance",
    "notol": "Tolerance not set",
    "nodata": "No planned values",
}


# ---------------------------------------------------------------- units

_UNIT_FACTORS = {
    "kg": ("mass", 1.0), "t": ("mass", 1000.0),
    "l": ("volume", 1.0), "ml": ("volume", 0.001),
}


def unit_kind(unit: str) -> str | None:
    """'mass' for kg/t, 'volume' for L/mL, None for anything else (for example bags)."""
    f = _UNIT_FACTORS.get((unit or "").strip().lower())
    return f[0] if f else None


def convert(quantity: float | None, from_unit: str, to_unit: str) -> float | None:
    """Convert between kg/t and L/mL. Same unit returns the quantity. Anything else returns None."""
    if quantity is None:
        return None
    f, t = (from_unit or "").strip(), (to_unit or "").strip()
    if f.lower() == t.lower():
        return quantity
    a, b = _UNIT_FACTORS.get(f.lower()), _UNIT_FACTORS.get(t.lower())
    if not a or not b or a[0] != b[0]:
        return None
    return quantity * a[1] / b[1]


# ---------------------------------------------------------------- strength

import math  # noqa: E402


def loaded_area_mm2(specimen_type: str, size_mm: float | None) -> float | None:
    """Loaded area: side² for a cube, π·d²/4 for a cylinder (size = side or diameter in mm)."""
    if not size_mm or size_mm <= 0:
        return None
    if (specimen_type or "").lower() == "cylinder":
        return math.pi * size_mm ** 2 / 4.0
    return size_mm ** 2


def strength_from_load(load_kn: float | None, area_mm2: float | None) -> float | None:
    """Compressive strength in N/mm² (= MPa) from failure load in kN and loaded area in mm²."""
    if load_kn is None or not area_mm2:
        return None
    return load_kn * 1000.0 / area_mm2


def strength_group(values: list[float], min_individual: float | None, min_mean: float | None) -> dict:
    """Summary of one age group and its check against the grade's acceptance values (if given)."""
    if not values:
        return {"n": 0, "mean": None, "min": None, "max": None, "status": "pending", "checks": []}
    mean = sum(values) / len(values)
    checks = []
    if min_mean is not None:
        checks.append(("Mean", mean >= min_mean, f"{mean:.2f} MPa, required ≥ {min_mean:g} MPa"))
    if min_individual is not None:
        low = min(values)
        checks.append(("Lowest individual", low >= min_individual, f"{low:.2f} MPa, required ≥ {min_individual:g} MPa"))
    if not checks:
        status = "noref"
    else:
        status = "pass" if all(ok for _, ok, _ in checks) else "fail"
    return {"n": len(values), "mean": mean, "min": min(values), "max": max(values), "status": status, "checks": checks}


STRENGTH_LABELS = {
    "pass": "Meets acceptance values",
    "fail": "Below acceptance values",
    "noref": "No acceptance values for this age",
    "pending": "Not tested yet",
}
