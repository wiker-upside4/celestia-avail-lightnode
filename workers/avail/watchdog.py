"""Avail LC watchdog. Cron every 5 minutes.

Detects sustained Avail submit failure (avail-light v1.13.3 has a sticky-endpoint
bug: when its broadcast WS RPC dies, it doesn't fail over to other endpoints in
config.yml and submit attempts time out forever). Automatically restarts the LC
to force fresh endpoint selection.

Trigger condition (all must hold):
  - Last N probes (window: 15 min) for da_layer='avail' AND submit_success=FALSE
  - AND ≥ FAIL_THRESHOLD probes attempted in window
  - AND no restart in last COOLDOWN minutes (avoid restart loop)

Action:
  - SSH avail-lightnode (internal IP) → `sudo systemctl restart avail-light`
  - Wait for /v2/status to be ready
  - Log to service_events table

Idempotent: throttled by COOLDOWN_MIN. Safe to run on every cron tick.
"""
import os
import subprocess
import sys
import time
import traceback

import requests

from workers.common import config
from workers.common.db import cursor, Json

# Tunables
WINDOW_MIN = 15            # look back this many minutes
FAIL_THRESHOLD = 3         # if >= this many fails in window AND 0 successes → restart
COOLDOWN_MIN = 30          # don't restart again within this many minutes

# Connection details
AVAIL_LN_HOST = os.environ.get("AVAIL_LN_HOST", "10.178.0.5")
SSH_KEY = os.path.expanduser("~/.ssh/dabeat_watchdog")
LC_STATUS_URL = f"{config.AVAIL_LC.rstrip('/')}/v2/status"
LC_HEALTH_TIMEOUT = 60     # max seconds to wait for /v2/status after restart


def recent_probe_stats():
    """Return (total, fails, last_attempt_ts) for the last WINDOW_MIN minutes."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE NOT submit_success),
                   MAX(ts)
            FROM probes
            WHERE da_layer = 'avail'
              AND ts > NOW() - INTERVAL %s
            """,
            (f"{WINDOW_MIN} minutes",),
        )
        return cur.fetchone()


def last_restart_age_min():
    """Minutes since last avail_lc_restart event. None if never."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT EXTRACT(EPOCH FROM (NOW() - MAX(ts))) / 60
            FROM service_events
            WHERE event_type = 'avail_lc_restart'
            """
        )
        v = cur.fetchone()[0]
        return float(v) if v is not None else None


def restart_lc(reason: str, details: dict) -> bool:
    """SSH and restart avail-light. Returns True if /v2/status comes back."""
    cmd = [
        "ssh",
        "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        f"wiker@{AVAIL_LN_HOST}",
        "sudo systemctl restart avail-light",
    ]
    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    restart_latency_s = time.perf_counter() - t0

    if r.returncode != 0:
        details["ssh_error"] = (r.stderr or "")[:300]
        log_event("avail_lc_restart_failed", reason, "high", details)
        return False

    # Wait for LC HTTP to come back
    deadline = time.time() + LC_HEALTH_TIMEOUT
    healthy = False
    while time.time() < deadline:
        try:
            resp = requests.get(LC_STATUS_URL, timeout=5)
            if resp.status_code == 200 and '"app"' in resp.text:
                healthy = True
                break
        except requests.RequestException:
            pass
        time.sleep(3)

    total_s = time.perf_counter() - t0
    details["restart_ssh_latency_s"] = round(restart_latency_s, 1)
    details["health_back_seconds"] = round(total_s, 1)
    details["healthy_after"] = healthy
    log_event(
        "avail_lc_restart" if healthy else "avail_lc_restart_unhealthy",
        reason, "info" if healthy else "high", details,
    )
    return healthy


def log_event(event_type: str, reason: str, severity: str, details: dict):
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO service_events (event_type, target, severity, reason, details)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (event_type, "avail-lightnode", severity, reason,
             Json(details) if details else None),
        )


def main():
    total, fails, last_attempt = recent_probe_stats()
    total = total or 0
    fails = fails or 0
    successes = total - fails

    if total < FAIL_THRESHOLD or fails < FAIL_THRESHOLD or successes > 0:
        print(f"[avail/watchdog] OK total={total} fails={fails} successes={successes}")
        return 0

    # All probes in window failed. Check cooldown.
    age = last_restart_age_min()
    if age is not None and age < COOLDOWN_MIN:
        print(f"[avail/watchdog] in cooldown: {age:.1f} min since last restart (need {COOLDOWN_MIN})")
        return 0

    reason = f"{fails}/{total} probes failed in last {WINDOW_MIN} min, no successes"
    details = {
        "window_min": WINDOW_MIN,
        "fails": fails,
        "successes": successes,
        "total": total,
        "last_attempt_ts": str(last_attempt) if last_attempt else None,
    }
    print(f"[avail/watchdog] TRIGGER restart: {reason}")
    healthy = restart_lc(reason, details)
    if healthy:
        print("[avail/watchdog] LC restarted successfully")
        return 0
    sys.stderr.write("[avail/watchdog] LC restart attempted but unhealthy\n")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
