"""Sensor register, readings, limits, plant API and AI review data."""
from datetime import date

from sqlalchemy import select

from app import sensors as sn
from app.db import SessionLocal
from app.models import SENSOR_TYPES, Sensor, SensorReading

H = {"Authorization": "Bearer test-token-123"}


def _sid(tag):
    with SessionLocal() as db:
        return db.scalars(select(Sensor).where(Sensor.tag == tag)).one().id


def test_check():
    assert sn.check(5, 2, 6) == "ok" and sn.check(1, 2, 6) == "low" and sn.check(7, 2, 6) == "high"
    assert sn.check(7, None, None) == "nolimit" and sn.check(7, None, 8) == "ok"


def test_sensor_register_and_readings(admin, client):
    page = admin.get("/sensors").text
    assert all(t in page for t in SENSOR_TYPES if t != "Other")
    assert "Photoelectric (presence / count)" in admin.get("/sensors/new?sensor_type=Photoelectric+%28presence+%2F+count%29").text
    # limits need a source; stage and type are required
    admin.get("/sensors/new")
    r = admin.post("/sensors/new", {"tag": "AG-MW-01", "name": "M-sand bin moisture", "low_limit": "2", "high_limit": "6"})
    assert r.status_code == 400 and "Select the plant stage." in r.text and "Select the sensor type." in r.text
    assert "Enter where the limits come from" in r.text and 'value="AG-MW-01"' in r.text
    r = admin.post("/sensors/new", {
        "tag": "AG-MW-01", "name": "M-sand bin moisture", "stage": "Raw material receipt and storage",
        "sensor_type": "Moisture (microwave)", "parameter": "Moisture of M-sand", "unit": "%", "make": "Hydronix",
        "model": "Hydro-Probe", "output": "4-20 mA analogue", "low_limit": "2", "high_limit": "6",
        "limit_source": "In-house test value for this check", "status": "In use"})
    assert r.status_code == 303
    sid = _sid("AG-MW-01")
    admin.get("/sensors/new")
    r = admin.post("/sensors/new", {"tag": "ag-mw-01", "name": "x", "stage": "Laboratory", "sensor_type": "Other"})
    assert r.status_code == 400 and "already used" in r.text
    admin.post("/sensors/new", {"tag": "PK-PE-01", "name": "Bag at spout", "stage": "Weighing and bag packing",
                                "sensor_type": "Photoelectric (presence / count)", "unit": "1/0"})
    # readings by hand
    admin.get(f"/sensors/{sid}")
    r = admin.post(f"/sensors/{sid}/reading", {"value": "4.5"})
    assert r.status_code == 303
    r = admin.post(f"/sensors/{sid}/reading", {"value": "7.2", "taken_at": "2026-10-22T09:30", "note": "after rain"})
    assert r.status_code == 303
    r = admin.post(f"/sensors/{sid}/reading", {"value": "abc"})
    assert r.status_code == 400 and "must be a number" in r.text
    r = admin.post(f"/sensors/{sid}/reading", {"value": "1", "taken_at": "2099-01-01T00:00"})
    assert r.status_code == 400 and "in the future" in r.text
    with SessionLocal() as db:
        res = sorted(x.result for x in db.scalars(select(SensorReading).where(SensorReading.sensor_id == sid)))
    assert res == ["high", "ok"]
    page = admin.get(f"/sensors/{sid}").text
    assert "Above high limit" in page and "after rain" in page and "Hydronix" in page
    page = admin.get("/sensors").text
    assert "Raw material receipt and storage" in page and "Weighing and bag packing" in page and "AG-MW-01" in page

    # plant API: all-or-nothing
    body = {"readings": [{"tag": "AG-MW-01", "value": 1.5}, {"tag": "PK-PE-01", "value": 1}]}
    assert client.post("/api/v1/sensor-readings", json=body).status_code == 401
    bad = {"readings": [{"tag": "AG-MW-01", "value": 3}, {"tag": "NOPE", "value": 1}]}
    r = client.post("/api/v1/sensor-readings", json=bad, headers=H)
    assert r.status_code == 422 and "no sensor with tag NOPE" in str(r.json())
    r = client.post("/api/v1/sensor-readings", json=body, headers=H)
    assert r.status_code == 200 and r.json()["saved"] == 2
    assert [x["result"] for x in r.json()["results"]] == ["low", "nolimit"]
    with SessionLocal() as db:
        assert db.query(SensorReading).filter(SensorReading.sensor_id == sid).count() == 3   # the rejected 3 was not saved
        d = sn.review_data(db, date(2000, 1, 1), date(2100, 1, 1), 100)
    assert {x["result"] for x in d["sensor_readings_outside_limits"]} == {"Below low limit", "Above high limit"}

    # editing limits keeps old results
    admin.get(f"/sensors/{sid}")
    r = admin.post(f"/sensors/{sid}", {"tag": "AG-MW-01", "name": "M-sand bin moisture", "stage": "Raw material receipt and storage",
                                       "sensor_type": "Moisture (microwave)", "unit": "%", "low_limit": "1", "high_limit": "8",
                                       "limit_source": "Revised", "status": "In use"})
    assert r.status_code == 303
    with SessionLocal() as db:
        assert db.get(Sensor, sid).high_limit == 8
        assert sorted(x.result for x in db.scalars(select(SensorReading).where(SensorReading.sensor_id == sid))) == ["high", "low", "ok"]


def test_sensor_permissions():
    from app.security import PERMISSIONS
    assert PERMISSIONS["sensors.reading"] == {"admin", "qc", "operator"}
    assert PERMISSIONS["sensors.write"] == {"admin", "qc"}
