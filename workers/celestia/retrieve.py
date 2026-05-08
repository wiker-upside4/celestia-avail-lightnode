"""Celestia self-probe retrieve worker. Cron every 5 minutes.

For each log-spaced age bucket, find probes whose age matches the bucket
window (±90s tolerance) and have not yet been retrieved at that bucket.
For each candidate, blob.GetAll(height, [namespace]) and check whether our
payload_hash appears among the returned blobs (data b64-decoded).

Result categories per (probe_id, bucket):
- success         : payload found, sha256 matches
- hash_mismatch   : data present but sha256 differs
- blob_not_found  : block has no matching blob in our namespace
- rpc_error       : RPC call failed
- timeout         : LC didn't respond
"""
import base64
import hashlib
import sys
import traceback

from workers.common.db import cursor, Json
from workers.common.rpc import CelestiaRPC

LN_INSTANCE = "celestia-A1"
NAMESPACE_HEX = "0000000000000000000000000000000000000000004441424541543031"
NAMESPACE_B64 = base64.standard_b64encode(bytes.fromhex(NAMESPACE_HEX)).decode()
TOLERANCE_SEC = 90

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
    with cursor() as cur:
        cur.execute(
            """
            SELECT p.probe_id, p.submit_height, p.payload_hash
            FROM probes p
            WHERE p.da_layer = 'celestia'
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


def check_block(rpc: CelestiaRPC, height: int, expected_hash: str) -> tuple[bool, str | None, int, int | None, str | None]:
    resp = rpc.call("blob.GetAll", [height, [NAMESPACE_B64]])
    if not resp.success:
        err_lower = (resp.error or "").lower()
        if "not found" in err_lower or "key not found" in err_lower:
            return False, "blob_not_found", resp.latency_ms, None, "no blobs in namespace"
        if resp.error_type == "timeout":
            return False, "timeout", resp.latency_ms, None, None
        return False, resp.error_type or "rpc_error", resp.latency_ms, None, (resp.error or "")[:120]

    blobs = resp.result or []
    if not isinstance(blobs, list):
        return False, "bad_response", resp.latency_ms, None, str(blobs)[:120]

    for b in blobs:
        b64data = b.get("data")
        if not b64data:
            continue
        try:
            raw = base64.standard_b64decode(b64data)
        except Exception:
            continue
        observed_hash = hashlib.sha256(raw).hexdigest()
        if observed_hash == expected_hash:
            return True, None, resp.latency_ms, len(raw), None

    if blobs:
        return False, "hash_mismatch", resp.latency_ms, None, f"{len(blobs)} blobs, none matched"
    return False, "blob_not_found", resp.latency_ms, None, "empty blob list"


def main():
    rpc = CelestiaRPC()
    summary: dict[str, dict[str, int]] = {}
    for label, age in BUCKETS:
        candidates = find_candidates(label, age)
        if not candidates:
            continue
        bs = {"checked": 0, "ok": 0, "fail": 0}
        for probe_id, height, payload_hash in candidates:
            ok, err, latency_ms, size, info = check_block(rpc, height, payload_hash)
            with cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO retrievals (
                        ts, probe_id, da_layer, ln_instance, attempt, bucket_label,
                        fetch_latency_ms, fetch_success, bytes_received, error_type, details
                    ) VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        probe_id, "celestia", LN_INSTANCE, 1, label,
                        latency_ms, ok, size, err,
                        Json({"info": info}) if info else None,
                    ),
                )
            bs["checked"] += 1
            bs["ok" if ok else "fail"] += 1
        summary[label] = bs

    if not summary:
        print("[celestia/retrieve] no candidates in any bucket")
        return 0
    parts = [f"{lbl}: {s['ok']}/{s['checked']} ok" for lbl, s in summary.items()]
    print(f"[celestia/retrieve] {' | '.join(parts)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
