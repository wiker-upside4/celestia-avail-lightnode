"""Celestia namespace activity monitor. Runs every minute via cron.

Calls blob.GetAll(height, [namespace]) for each active monitored namespace.
Skips rows with placeholder values that haven't been populated.
"""
import base64
import sys
import traceback

from workers.common import config
from workers.common.db import cursor, Json
from workers.common.rpc import CelestiaRPC

MAX_BLOCKS_PER_NAMESPACE_PER_RUN = 50


def _is_placeholder(ns: str) -> bool:
    return ns.startswith("PLACEHOLDER_") or len(ns) < 20


def _to_b64_namespace(ns: str) -> str:
    """Convert hex (or raw) namespace string to base64 form expected by blob.GetAll."""
    s = ns.strip()
    if s.startswith("0x"):
        s = s[2:]
    try:
        raw = bytes.fromhex(s)
    except ValueError:
        # Already base64? return as-is.
        return ns
    return base64.standard_b64encode(raw).decode()


def get_active_namespaces():
    with cursor() as cur:
        cur.execute(
            """
            SELECT namespace_or_appid FROM monitored_namespaces
            WHERE da_layer = 'celestia' AND active = TRUE
            """
        )
        return [row[0] for row in cur.fetchall()]


def get_last_height_for(namespace):
    with cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(MAX(height), 0) FROM namespace_observations
            WHERE da_layer = 'celestia' AND namespace_or_appid = %s
            """,
            (namespace,),
        )
        return cur.fetchone()[0]


def get_local_head(rpc):
    resp = rpc.call("header.LocalHead")
    if not resp.success:
        return None
    return int(resp.result["header"]["height"])


def main():
    namespaces = get_active_namespaces()
    if not namespaces:
        print("[celestia/namespace_mon] no active namespaces")
        return 0

    rpc = CelestiaRPC()
    local_head = get_local_head(rpc)
    if local_head is None:
        sys.stderr.write("[celestia/namespace_mon] cannot get local head\n")
        return 1

    inserted = 0
    for ns in namespaces:
        if _is_placeholder(ns):
            sys.stderr.write(f"[celestia/namespace_mon] skipping placeholder ns={ns}\n")
            continue
        last = get_last_height_for(ns)
        start = max(last + 1, local_head - 100)  # don't backfill too far on first run
        end = min(local_head, start + MAX_BLOCKS_PER_NAMESPACE_PER_RUN - 1)
        if start > local_head:
            continue
        ns_b64 = _to_b64_namespace(ns)
        for h in range(start, end + 1):
            resp = rpc.call("blob.GetAll", [h, [ns_b64]])
            blob_count = 0
            total_bytes = 0
            commitments = []
            success = True
            error_type = None
            details = {}

            if resp.success:
                blobs = resp.result or []
                if isinstance(blobs, list):
                    blob_count = len(blobs)
                    for b in blobs:
                        # blob payload size: data is base64
                        data = b.get("data")
                        if data:
                            try:
                                total_bytes += len(base64.standard_b64decode(data))
                            except Exception:
                                pass
                        c = b.get("commitment")
                        if c:
                            commitments.append(c)
            else:
                # blob.GetAll returns error when no blobs found OR when sync lag etc.
                # Treat 'blob: not found' as success with zero blobs.
                err = (resp.error or "").lower()
                if "not found" in err or "no blobs" in err:
                    success = True
                    blob_count = 0
                else:
                    success = False
                    error_type = resp.error_type
                    details["error"] = resp.error[:200] if resp.error else None

            with cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO namespace_observations (
                        ts, da_layer, ln_instance, namespace_or_appid, height,
                        blob_count, total_bytes, commitments,
                        fetch_latency_ms, fetch_success, error_type, details
                    ) VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (da_layer, namespace_or_appid, height, ts) DO NOTHING
                    """,
                    (
                        "celestia", config.CELESTIA_LN_INSTANCE, ns, h,
                        blob_count, total_bytes, commitments,
                        resp.latency_ms, success, error_type,
                        Json(details) if details else None,
                    ),
                )
                inserted += 1
    print(f"[celestia/namespace_mon] inserted {inserted} observations across {len(namespaces)} namespaces")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
