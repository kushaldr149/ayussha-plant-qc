# Connecting the app to the plant control system

## Current position

The weighing, dosing, conveying, mixing and bagging equipment is run by the plant's own control system
(PLC/SCADA), supplied by the equipment supplier. This app does not control any machine. It receives
production data from that system and keeps the QC and traceability records.

The equipment supplier is not finalised yet, so the data interface is not known. Ask the supplier which
of these their system offers, and request the documentation:

| Interface | What it means for this app |
|---|---|
| OPC UA | A small bridge program reads batch values from the OPC UA server and posts them to the app's API. |
| Modbus TCP | The same, reading registers the supplier documents (register map needed). |
| Database (SQL Server, MySQL and similar) | A bridge program reads the supplier's batch table and posts new rows to the API. |
| CSV / Excel export | Files can be imported now through **Production log → Import CSV**, or picked up automatically by a bridge program. |

Questions to ask the supplier:

1. Which interface does the batching/bagging control system provide for reading batch reports?
2. Which values are available per batch: planned and actual weight per bin/silo, batch number, time, bag count, bag weights?
3. How is each bin or silo identified, and can the material lot loaded into it be recorded?
4. Is the interface read-only, and can it be reached from a separate PC on the plant network?

Keep the connection read-only: the app should read from the control system, never write to it.

## What the app already provides

### CSV import

**Production log → Import CSV**. Template columns:

```
date,shift,record_no,product_line,material,lot_no,planned,actual,unit,bags,bag_target_kg,total_actual_kg,remarks
```

One row per material; rows with the same `record_no` become one production record. `material` must match
a material name in Setup exactly (upper/lower case is ignored).

### API for a bridge program

Set `PLANT_API_TOKEN` in `.env` to a long random value and restart. Then:

```
POST /api/v1/production-records
Authorization: Bearer <PLANT_API_TOKEN>
Content-Type: application/json

{
  "date": "2026-11-02",
  "shift": "A",
  "record_no": "BATCH-000123",
  "product_line": "Coated coarse aggregate",
  "bags": 40,
  "bag_target_kg": 1000,
  "total_actual_kg": 40120,
  "components": [
    {"material": "<material name as in Setup>", "lot_no": "<lot>", "planned": 1000.0, "actual": 1003.0, "unit": "kg"}
  ]
}
```

The values above only show the format. The response gives the record number, tolerance status and whether
any lot was not accepted. A record number that already exists is refused, so a bridge program can safely
resend a batch after a network failure. The full API description is at `/api/docs` on the running app.

## Next step

Once the supplier confirms the interface and shares its documentation, the bridge program can be written
for that interface and tested against the supplier's system or simulator.
