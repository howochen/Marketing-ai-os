#!/bin/sh
# Rehearsal-only boundary. Production backup policy is a separate gate.
set -eu
umask 077
case "${PGDATABASE:-}" in mos_p05_dr_source_*) ;; *) echo 'Refusing non-drill source' >&2; exit 2;; esac
out=${1:?Backup output required}
case "$out" in /tmp/mos-p05-backups/*.dump) ;; *) echo 'Refusing output location' >&2; exit 2;; esac
dir=/tmp/mos-p05-backups
test "$(dirname "$out")" = "$dir" || exit 2
test ! -L "$dir" || exit 2
mkdir -p "$dir"
test "$(stat -c %u "$dir")" = "$(id -u)" || exit 2
chmod 700 "$dir"
test ! -e "$out" || { echo 'Backup already exists' >&2; exit 2; }
tmp=$(mktemp "$dir/.partial.XXXXXX")
trap 'rm -f "$tmp"' EXIT HUP INT TERM
pg_dump --format=custom --file="$tmp"
pg_restore --list "$tmp" >/dev/null
chmod 600 "$tmp"
ln "$tmp" "$out"
echo 'Backup complete'
