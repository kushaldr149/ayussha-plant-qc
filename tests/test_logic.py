import pytest

from app import logic
from app.security import hash_password, password_problem, verify_password


@pytest.mark.parametrize("value,mn,mx,expected", [
    (None, 1, 2, "missing"),
    (5, None, None, "nolimit"),
    (1, 1, 2, "pass"),          # limits are inclusive
    (2, 1, 2, "pass"),
    (0.999, 1, 2, "fail"),
    (2.001, 1, 2, "fail"),
    (100, 50, None, "pass"),
    (49, 50, None, "fail"),
    (10, None, 10, "pass"),
    (10.5, None, 10, "fail"),
])
def test_evaluate(value, mn, mx, expected):
    assert logic.evaluate(value, mn, mx) == expected


def test_overall():
    assert logic.overall_status([]) == "incomplete"
    assert logic.overall_status(["pass", "nolimit"]) == "pass"
    assert logic.overall_status(["pass", "missing"]) == "incomplete"
    assert logic.overall_status(["missing", "fail"]) == "fail"


def test_deviation_and_status():
    assert logic.deviation_pct(100, 102) == pytest.approx(2.0)
    assert logic.deviation_pct(100, 97) == pytest.approx(-3.0)
    assert logic.deviation_pct(None, 5) is None
    assert logic.deviation_pct(0, 5) is None
    assert logic.production_status([2.0, -3.0], 2.5) == ("over", 3.0)
    assert logic.production_status([2.0, -1.0], 2.5) == ("ok", 2.0)
    assert logic.production_status([2.0], None) == ("notol", 2.0)
    assert logic.production_status([None], 2) == ("nodata", None)


def test_accept_needs_remark():
    assert logic.accept_needs_remark("fail", "Accepted", "")
    assert not logic.accept_needs_remark("fail", "Accepted", "Concession approved by QM")
    assert not logic.accept_needs_remark("fail", "Rejected", "")
    assert not logic.accept_needs_remark("pass", "Accepted", "")


def test_parse_number():
    assert logic.parse_number("") is None
    assert logic.parse_number(" 1,250.5 ") == 1250.5
    with pytest.raises(ValueError):
        logic.parse_number("abc")
    with pytest.raises(ValueError):
        logic.parse_number("nan")


def test_limit_text():
    assert logic.limit_text(1, 2, "%") == "1 – 2 %"
    assert logic.limit_text(30, None, "min") == "≥ 30 min"
    assert logic.limit_text(None, 10, "") == "≤ 10"
    assert logic.limit_text(None, None) == "No limit set"


def test_passwords():
    h = hash_password("Correct12Horse")
    assert verify_password("Correct12Horse", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", "garbage")
    assert password_problem("short") is not None
    assert password_problem("alllowercase123") is not None
    assert password_problem("GoodPassword9") is None
