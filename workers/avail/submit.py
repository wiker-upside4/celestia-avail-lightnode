"""Avail self-probe submit worker. Cron every 1 minute.

Generates a unique payload (timestamp + random nonce), submits via /v2/submit,
records probe metadata + payload_hash in `probes` table.

Idempotent across cron firings: each run generates a fresh payload, so duplicate
firings yield independent probes (acceptable for cadence ≤1/min).

Failures recorded with submit_success=FALSE and classified error_type.
"""
import base64
import hashlib
import os
import secrets
import sys
import time
import traceback

import requests

from workers.common import config
from workers.common.db import cursor, Json

APP_ID = "46"
LN_INSTANCE = "avail-A1"
SUBMIT_TIMEOUT_SEC = 60


def make_payload() -> tuple[str, bytes, str]:
    """Returns (raw_str, raw_bytes_for_b64, sha256_hex)."""
    ts = int(time.time())
    nonce = secrets.token_hex(8)
    raw = f"dabeat-{ts}-{nonce}".encode()
    digest = hashlib.sha256(raw).hexdigest()
    return raw.decode(), raw, digest


def main():
    raw_str, raw_bytes, payload_hash = make_payload()
    payload_b64 = base64.standard_b64encode(raw_bytes).decode()

    url = f"{config.AVAIL_LC.rstrip('/')}/v2/submit"
    body = {"data": payload_b64}

    submit_success = False
    error_type = None
    block_number = None
    block_hash = None
    tx_hash = None
    index = None
    latency_ms = None
    details: dict = {}

    start = time.perf_counter()
    try:
        r = requests.post(url, json=body, timeout=SUBMIT_TIMEOUT_SEC)
        latency_ms = int((time.perf_counter() - start) * 1000)
        if r.status_code != 200:
            error_type = f"http_{r.status_code}"
            details["body"] = r.text[:300]
        else:
            try:
                resp = r.json()
                block_number = resp.get("block_number")
                block_hash = resp.get("block_hash")
                tx_hash = resp.get("hash")
                index = resp.get("index")
                if block_number is not None:
                    submit_success = True
                else:
                    error_type = "no_block_number"
                    details["resp"] = resp
            except ValueError:
                error_type = "non_json"
                details["body"] = r.text[:300]
    except requests.exceptions.Timeout:
        latency_ms = int((time.perf_counter() - start) * 1000)
        error_type = "timeout"
    except requests.exceptions.ConnectionError as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        error_type = "connection"
        details["error"] = str(e)[:200]
    except requests.RequestException as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        error_type = "request"
        details["error"] = str(e)[:200]

    # Always record the probe (success or fail) for visibility
    if submit_success:
        details["block_hash"] = block_hash
        details["index"] = index
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO probes (
                da_layer, ln_instance, namespace_or_appid,
                payload_size_bytes, payload_hash,
                submit_height, submit_tx_hash, submit_latency_ms,
                submit_success, error_type, details
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING probe_id, ts
            """,
            (
                "avail", LN_INSTANCE, APP_ID,
                len(raw_bytes), payload_hash,
                block_number, tx_hash, latency_ms,
                submit_success, error_type, Json(details) if details else None,
            ),
        )
        probe_id, ts = cur.fetchone()

    if submit_success:
        print(f"[avail/submit] OK probe_id={probe_id} block={block_number} latency={latency_ms}ms")
    else:
        print(f"[avail/submit] FAIL probe_id={probe_id} error={error_type} latency={latency_ms}ms")
        sys.stderr.write(f"[avail/submit] failed: {error_type} details={details}\n")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
