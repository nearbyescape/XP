#!/bin/sh
# Periodic pg_dump of the signal ledger (custom format, restore with pg_restore).
# Runs inside the `backup` service; files land in ./backups on the host.
set -u
keep="${BACKUP_KEEP_DAYS:-14}"
every=$(( ${BACKUP_INTERVAL_HOURS:-24} * 3600 ))
while true; do
  file="/backups/${PGDATABASE}-$(date -u +%Y%m%dT%H%MZ).dump"
  if pg_dump -Fc -f "$file.part"; then
    mv "$file.part" "$file"
    echo "backup ok: $file ($(du -h "$file" | cut -f1))"
  else
    rm -f "$file.part"
    echo "backup FAILED for ${PGDATABASE}" >&2
  fi
  find /backups -name "${PGDATABASE}-*.dump" -mtime +"$keep" -delete
  sleep "$every"
done
