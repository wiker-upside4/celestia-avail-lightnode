"""Avail light client health worker. Runs every minute via cron."""
import sys
import traceback

from workers.common import config
from workers.common.db import cursor, Json
from workers.common.rpc import AvailLC


def collect():
    lc = AvailLC()
    details = {}
    network_head = local_head = None
    sync_lag = None
    is_syncing = None
    block_confidence = None
    rpc_success = True

    st = lc.get("/v2/status")
    if st.success:
        r = st.result
        blocks = r.get("blocks") or {}
        local_head = blocks.get("latest")
        avail = blocks.get("available") or {}
        last_avail = avail.get("last")
        if local_head is not None and last_avail is not None:
            sync_lag = max(local_head - last_avail, 0)
            is_syncing = sync_lag > 1
        # network_head: same as local_head for an LC
        network_head = local_head
        details["modes"] = r.get("modes")
        details["network"] = r.get("network")
        details["available"] = avail
    else:
        rpc_success = False
        details["status_error"] = st.error_type

    # Confidence sample: query the latest available block's status
    if rpc_success and details.get("available", {}).get("last"):
        last_avail_h = details["available"]["last"]
        bs = lc.get(f"/v2/blocks/{last_avail_h}")
        if bs.success:
            block_confidence = bs.result.get("confidence")
            details["block_status"] = bs.result.get("status")

    ver = lc.get("/v2/version")
    if ver.success:
        details["version"] = ver.result

    rpc_latency_ms = st.latency_ms

    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO node_health (
                ts, da_layer, ln_instance,
                network_head, local_head, sampled_head, sync_lag, is_syncing,
                das_running, das_concurrency, das_failed_samples,
                block_confidence, peers_count, bandwidth_in_total, bandwidth_out_total,
                rate_in, rate_out, rpc_latency_ms, rpc_success, details
            ) VALUES (
                NOW(), %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            (
                "avail", config.AVAIL_LN_INSTANCE,
                network_head, local_head, None, sync_lag, is_syncing,
                None, None, None,
                block_confidence, None, None, None,
                None, None, rpc_latency_ms, rpc_success,
                Json(details) if details else None,
            ),
        )


if __name__ == "__main__":
    try:
        collect()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
