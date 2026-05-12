#!/bin/bash
# Install/refresh DABEAT cron jobs for the current user. Idempotent.

set -euo pipefail

PYTHON=/home/wiker/.dabeat/venv/bin/python
PROJ=/home/wiker/dabeat
LOGS=$PROJ/logs
BACKUPS=$PROJ/backups

mkdir -p "$LOGS" "$BACKUPS"

CRON_BLOCK_BEGIN="# >>> dabeat cron (managed) >>>"
CRON_BLOCK_END="# <<< dabeat cron (managed) <<<"

NEW_BLOCK=$(cat <<EOF
$CRON_BLOCK_BEGIN
PYTHONPATH=$PROJ
* * * * * $PYTHON -m workers.celestia.health     >>$LOGS/celestia_health.log     2>&1
* * * * * $PYTHON -m workers.celestia.header     >>$LOGS/celestia_header.log     2>&1
* * * * * $PYTHON -m workers.celestia.namespace_mon >>$LOGS/celestia_ns.log      2>&1
* * * * * $PYTHON -m workers.celestia.shares_check   >>$LOGS/celestia_shares.log  2>&1
* * * * * $PYTHON -m workers.celestia.fraud_monitor  >>$LOGS/celestia_fraud.log   2>&1
* * * * * $PYTHON -m workers.avail.health        >>$LOGS/avail_health.log        2>&1
* * * * * $PYTHON -m workers.avail.header        >>$LOGS/avail_header.log        2>&1
* * * * * $PYTHON -m workers.avail.app_id_mon    >>$LOGS/avail_app_id.log        2>&1
* * * * * $PYTHON -m workers.avail.availability_check >>$LOGS/avail_availability.log 2>&1
*/5 * * * * $PYTHON -m workers.avail.submit          >>$LOGS/avail_submit.log         2>&1
*/5 * * * * $PYTHON -m workers.avail.retrieve        >>$LOGS/avail_retrieve.log       2>&1
*/5 * * * * $PYTHON -m workers.avail.watchdog        >>$LOGS/avail_watchdog.log       2>&1
* * * * * $PYTHON -m workers.celestia.submit         >>$LOGS/celestia_submit.log      2>&1
*/5 * * * * $PYTHON -m workers.celestia.retrieve     >>$LOGS/celestia_retrieve.log    2>&1
0 0 * * * df -h >>$LOGS/disk_usage.log 2>&1
0 3 * * * $PROJ/scripts/backup.sh >>$LOGS/backup.log 2>&1
$CRON_BLOCK_END
EOF
)

# Strip any existing managed block, then append the new one.
EXISTING=$(crontab -l 2>/dev/null || true)
FILTERED=$(printf '%s\n' "$EXISTING" | awk -v b="$CRON_BLOCK_BEGIN" -v e="$CRON_BLOCK_END" '
    BEGIN { skip=0 }
    $0==b { skip=1; next }
    $0==e { skip=0; next }
    !skip { print }
')

{ printf '%s\n' "$FILTERED"; printf '%s\n' "$NEW_BLOCK"; } | crontab -

echo "[install_cron] DABEAT cron block installed."
crontab -l
