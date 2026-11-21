#!/usr/bin/env bash
# CHIP off-VM backup: encrypted full pg_dump of the live `places` database streamed to
# Google Drive through the rclone crypt remote `chip-crypt:` (gdrive:CHIP-backups).
# Nightly copy kept 7 days; Sunday's copy also kept 4 weeks. On Sundays the source
# archives (data/ingest) and recovery records (data/deploy-recovery) are synced too.
# Restore: see infra/backup/README.md. The crypt passwords are in
# ~/.config/chip-backup/RECOVERY-PASSWORDS.txt and must also be kept off the VM.
set -euo pipefail

REMOTE=${CHIP_BACKUP_REMOTE:-chip-crypt:}
APP=/home/john/places-app
LOG_DIR=/home/john/.local/state/chip-backup
mkdir -p "$LOG_DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DOW=$(date -u +%u)   # 7 = Sunday

DB_URL=$(cd "$APP/backend" && .venv/bin/python -W ignore -c \
  "from app.db import DATABASE_URL as u; print(u.replace('+psycopg', ''))" 2>/dev/null)

echo "$STAMP start" >> "$LOG_DIR/runs.log"

# Stream the dump; rclone encrypts client-side. No local temp file.
pg_dump -Fc -Z 6 "$DB_URL" \
  | tee >(wc -c > "$LOG_DIR/last-bytes.txt") \
  | rclone rcat --drive-chunk-size 64M "${REMOTE}db/daily/places-$STAMP.dump"
sleep 2
DUMPED=$(tr -d ' ' < "$LOG_DIR/last-bytes.txt")

# Confirm the upload: decrypted size equals the bytes pg_dump wrote, and the
# table of contents (at the start of the file) reads back.
SIZE=$(rclone size --json "${REMOTE}db/daily/places-$STAMP.dump" | sed -n 's/.*"bytes":\([0-9]*\).*/\1/p')
if [ "$SIZE" != "$DUMPED" ]; then
  echo "$STAMP FAILED size remote=$SIZE dumped=$DUMPED" >> "$LOG_DIR/runs.log"; exit 1
fi
rclone cat --count 268435456 "${REMOTE}db/daily/places-$STAMP.dump" > "$LOG_DIR/last-head.dump"
pg_restore --list "$LOG_DIR/last-head.dump" > "$LOG_DIR/last-toc.txt" 2>/dev/null || true
rm -f "$LOG_DIR/last-head.dump"
ENTRIES=$(grep -vc '^;' "$LOG_DIR/last-toc.txt" || true)
if [ "${ENTRIES:-0}" -lt 100 ]; then
  echo "$STAMP FAILED toc entries=$ENTRIES" >> "$LOG_DIR/runs.log"; exit 1
fi

if [ "$DOW" = 7 ]; then
  rclone copyto "${REMOTE}db/daily/places-$STAMP.dump" "${REMOTE}db/weekly/places-$STAMP.dump"
  rclone sync "$APP/data/ingest" "${REMOTE}files/ingest" --exclude 'node_modules/**'
  rclone sync "$APP/data/deploy-recovery" "${REMOTE}files/deploy-recovery"
fi

# Retention.
# (The weekly folder does not exist until the first Sunday run; skip a missing folder.)
for spec in "daily 8d" "weekly 29d"; do
  set -- $spec
  if rclone lsf "${REMOTE}db/$1" >/dev/null 2>&1; then
    rclone delete --min-age "$2" "${REMOTE}db/$1"
  fi
done

echo "$STAMP ok entries=$ENTRIES bytes=$SIZE" >> "$LOG_DIR/runs.log"
