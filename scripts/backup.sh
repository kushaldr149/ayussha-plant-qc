#!/bin/sh
# Back up the SQLite database safely while the app is running.
# Usage on the server (from the project folder):   docker compose exec plantqc sh scripts/backup.sh
# The copy is written to the data folder as backups/plantqc-YYYYMMDD-HHMM.db.
# Copy that folder to another disk or machine regularly; a backup on the same disk does not protect against disk failure.
set -eu
DATA_DIR="${DATA_DIR:-./data}"
mkdir -p "$DATA_DIR/backups"
STAMP=$(date +%Y%m%d-%H%M)
OUT="$DATA_DIR/backups/plantqc-$STAMP.db"
sqlite3 "$DATA_DIR/plantqc.db" ".backup '$OUT'"
echo "Backup written to $OUT"
# Keep the 30 most recent backups.
ls -1t "$DATA_DIR"/backups/plantqc-*.db 2>/dev/null | tail -n +31 | xargs -r rm -f
