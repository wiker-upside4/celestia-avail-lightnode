"""Avail self-probe retrieve worker. Cron every 5 minutes.

For each log-spaced age bucket, find probes whose age matches the bucket
window (±90s tolerance) and have not yet been retrieved at that bucket.
For each candidate, GET /v2/blocks/{height}/data?fields=data and check if
our payload_hash appears among data_transactions[*].data (base64-decoded).

Result categories per (probe_id, bucket):
- success         : payload found, sha256 matches
- hash_mismatch   : data present but sha256 differs (anomaly)
- blob_not_found  : block has no matching payload
- rpc_error       : HTTP error from LC
- timeout         : LC didn't respond in time
"""
import base64
import hashlib
import sys
import time
import traceback
from datetime import timedelta

import requests

from workers.common import config
from workers.common.db import cursor, Json

LN_INSTANCE = "avail-A1"
TOLERANCE_SEC = 90
HTTP_TIMEOUT_SEC = 30

# (label, age_seconds)
BUCKETS = [
    ("5m", 5 * 60),
    ("15m", 15 * 60),
    ("1h", 60 * 60),
    ("6h", 6 * 60 * 60),
    ("1d", 24 * 60 * 60),
    ("3d", 3 * 24 * 60 * 60),
    ("7d", 7 * 24 * 60 * 60),
    ("14d", 14 * 24 * 60 * 60),
    ("30d", 30 * 24 * 60 * 60),
]


def find_candidates(label: str, age_sec: int) -> list[tuple[int, int, str]]:
    """Return list of (probe_id, submit_height, payload_hash) for candidates."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT p.probe_id, p.submit_height, p.payload_hash
            FROM probes p
            WHERE p.da_layer = 'avail'
              AND p.submit_success = TRUE
              AND p.submit_height IS NOT NULL
              AND p.payload_hash IS NOT NULL
              AND p.ts BETWEEN NOW() - %s::interval - INTERVAL '%s seconds'
                           AND NOW() - %s::interval + INTERVAL '%s seconds'
              AND NOT EXISTS (
                SELECT 1 FROM retrievals r
                WHERE r.probe_id = p.probe_id
                  AND r.bucket_label = %s
                  AND r.ln_instance = %s
              )
            ORDER BY p.ts
            """,
            (
                f"{age_sec} seconds", TOLERANCE_SEC,
                f"{age_sec} seconds", TOLERANCE_SEC,
                label, LN_INSTANCE,
            ),
        )
        return cur.fetchall()


def check_block(height: int, expected_hash: str) -> tuple[bool, str | None, int, int | None, str | None]:
    """Return (success, error_type, latency_ms, bytes_received, hash_match_str)."""
    url = f"{config.AVAIL_LC.rstrip('/')}/v2/blocks/{height}/data?fields=data"
    start = time.perf_counter()
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT_SEC)
        latency_ms = int((time.perf_counter() - start) * 1000)
    except requests.exceptions.Timeout:
        return False, "timeout", int((time.perf_counter() - start) * 1000), None, None
    except requests.exceptions.ConnectionError:
        return False, "connection", int((time.perf_counter() - start) * 1000), None, None
    except requests.RequestException as e:
        return False, "request", int((time.perf_counter() - start) * 1000), None, str(e)[:80]

    if r.status_code == 404:
        return False, "blob_not_found", latency_ms, None, "block_404"
    if r.status_code != 200:
        return False, f"http_{r.status_code}", latency_ms, None, r.text[:120]

    try:
        body = r.json()
    except ValueError:
        return False, "non_json", latency_ms, None, r.text[:120]

    txs = body.get("data_transactions") or []
    found_match = False
    matched_size = None
    for tx in txs:
        b64data = tx.get("data")
        if not b64data:
            continue
        try:
            raw = base64.standard_b64decode(b64data)
        except Exception:
            continue
        observed_hash = hashlib.sha256(raw).hexdigest()
        if observed_hash == expected_hash:
            found_match = True
            matched_size = len(raw)
            break

    if found_match:
        return True, None, latency_ms, matched_size, None
    if txs:
        # tx present in block but none matched
        return False, "hash_mismatch", latency_ms, None, f"{len(txs)} txs, none matched"
    return False, "blob_not_found", latency_ms, None, "no data_transactions"


def main():
    summary: dict[str, dict[str, int]] = {}
    for label, age in BUCKETS:
        candidates = find_candidates(label, age)
        if not candidates:
            continue
        bucket_summary = {"checked": 0, "ok": 0, "fail": 0}
        for probe_id, height, payload_hash in candidates:
            ok, err, latency_ms, size, mismatch_info = check_block(height, payload_hash)
            with cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO retrievals (
                        ts, probe_id, da_layer, ln_instance, attempt, bucket_label,
                        fetch_latency_ms, fetch_success, bytes_received, error_type, details
                    ) VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        probe_id, "avail", LN_INSTANCE, 1, label,
                        latency_ms, ok, size, err,
                        Json({"info": mismatch_info}) if mismatch_info else None,
                    ),
                )
            bucket_summary["checked"] += 1
            bucket_summary["ok" if ok else "fail"] += 1
        summary[label] = bucket_summary

    if not summary:
        print("[avail/retrieve] no candidates in any bucket")
        return 0
    parts = [f"{lbl}: {s['ok']}/{s['checked']} ok" for lbl, s in summary.items()]
    print(f"[avail/retrieve] {' | '.join(parts)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
