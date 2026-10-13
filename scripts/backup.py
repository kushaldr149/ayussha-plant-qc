"""Back up the SQLite database safely while the app is running (works on Windows, Linux and macOS).

Usage:  python scripts/backup.py
Writes  <DATA_DIR>/backups/plantqc-YYYYMMDD-HHMM.db  and keeps the 30 most recent backups.
Copy the backups folder to another drive or machine regularly.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
data_dir = Path(os.environ.get("DATA_DIR") or ROOT / "data")
source = data_dir / "plantqc.db"
if not source.exists():
    sys.exit(f"No database found at {source}")
out_dir = data_dir / "backups"
out_dir.mkdir(parents=True, exist_ok=True)
target = out_dir / f"plantqc-{datetime.now():%Y%m%d-%H%M}.db"

src = sqlite3.connect(source)
dst = sqlite3.connect(target)
with dst:
    src.backup(dst)
dst.close()
src.close()
print(f"Backup written to {target}")

backups = sorted(out_dir.glob("plantqc-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
for old in backups[30:]:
    old.unlink()
