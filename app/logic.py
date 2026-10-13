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


def evaluate(value: float | None, min_value: float | None, max_value: float | None) -> str:
    """Status of one test value against its limits: pass, fail, missing or nolimit."""
    if value is None:
        return "missing"
    if min_value is None and max_value is None:
        return "nolimit"
    if min_value is not None and value < min_value:
        return "fail"
    if max_value is not None and value > max_value:
        return "fail"
    return "pass"


def overall_status(statuses: Iterable[str]) -> str:
    """Overall result of a test: fail if any value is out of limit, incomplete if any is missing."""
    statuses = list(statuses)
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
}

PRODUCTION_LABELS = {
    "ok": "Within tolerance",
    "over": "Over tolerance",
    "notol": "Tolerance not set",
    "nodata": "No planned values",
}
