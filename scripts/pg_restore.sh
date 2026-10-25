#!/bin/sh
set -eu
umask 077
case "${PGDATABASE:-}" in mos_p05_dr_restore_*) ;; *) echo 'Refusing non-drill target' >&2; exit 2;; esac
archive=${1:?Archive required}
case "$archive" in /tmp/mos-p05-backups/*.dump) ;; *) echo 'Refusing archive location' >&2; exit 2;; esac
test "$(dirname "$archive")" = /tmp/mos-p05-backups || exit 2
pg_restore --list "$archive" >/dev/null
# createdb fails if target exists; never --clean, DROP, or overwrite a live database.
createdb "$PGDATABASE"
pg_restore --exit-on-error --single-transaction --no-owner --dbname="$PGDATABASE" "$archive"
echo 'Restore complete'
