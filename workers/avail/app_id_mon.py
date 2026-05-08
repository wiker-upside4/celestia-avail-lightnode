"""Avail app_id activity monitor. Runs every minute via cron.

Avail LC runs in light (non-app) mode, so /v2/blocks/{n}/data returns 404.
Instead we read the block header's extension.app_lookup which lists app_ids
present in each block along with their position. This gives us blob_count
and total bytes (via app_lookup.size) per block, but not the actual blob payloads.
"""
import sys
import traceback

from workers.common import config
from workers.common.db import cursor, Json
from workers.common.rpc import AvailLC

MAX_BLOCKS_PER_APP_PER_RUN = 50


def get_active_app_ids():
    with cursor() as cur:
        cur.execute(
            """
            SELECT namespace_or_appid FROM monitored_namespaces
            WHERE da_layer = 'avail' AND active = TRUE
            """
        )
        return [row[0] for row in cur.fetchall()]


def get_last_height_for(app_id):
    with cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(MAX(height), 0) FROM namespace_observations
            WHERE da_layer = 'avail' AND namespace_or_appid = %s
            """,
            (app_id,),
        )
        return cur.fetchone()[0]


def main():
    app_ids = get_active_app_ids()
    if not app_ids:
        print("[avail/app_id_mon] no active app_ids")
        return 0

    lc = AvailLC()
    st = lc.get("/v2/status")
    if not st.success:
        sys.stderr.write(f"[avail/app_id_mon] status failed: {st.error_type}\n")
        return 1
    avail = (st.result.get("blocks") or {}).get("available") or {}
    first_avail = avail.get("first")
    last_avail = avail.get("last")
    if first_avail is None or last_avail is None:
        return 0

    inserted = 0
    # Determine block range to scan: union of all app_ids' progress
    min_last = None
    for a in app_ids:
        h = get_last_height_for(a)
        if min_last is None or h < min_last:
            min_last = h
    if min_last == 0:
        scan_start = max(last_avail - 30, first_avail)
    else:
        scan_start = max(min_last + 1, first_avail)
    scan_end = min(last_avail, scan_start + MAX_BLOCKS_PER_APP_PER_RUN - 1)
    if scan_start > last_avail:
        return 0

    # For each block in range, fetch header once and observe all monitored app_ids
    consecutive_failures = 0
    for h in range(scan_start, scan_end + 1):
        resp = lc.get(f"/v2/blocks/{h}/header")
        if not resp.success:
            sys.stderr.write(f"[avail/app_id_mon] block {h} header failed: {resp.error_type}\n")
            if resp.error_type in ("not_found",):
                continue
            consecutive_failures += 1
            if consecutive_failures >= 3:
                break
            continue
        consecutive_failures = 0
        d = resp.result
        ext = d.get("extension") or {}
        app_lookup = ext.get("app_lookup") or {}
        index = app_lookup.get("index") or []
        block_total_size = app_lookup.get("size") or 0

        # Build map: app_id -> count of entries present in block (each entry is one blob slot)
        # And approximate per-app bytes by next_start - this_start in app_lookup index.
        # If only one entry, that app gets all of block_total_size.
        app_present = {}
        for i, entry in enumerate(index):
            aid = entry.get("appId")
            if aid is None:
                continue
            start = entry.get("start", 0)
            next_start = index[i + 1]["start"] if i + 1 < len(index) else block_total_size
            size = max(next_start - start, 0)
            key = str(aid)
            agg = app_present.setdefault(key, {"blob_count": 0, "total_bytes": 0})
            agg["blob_count"] += 1
            agg["total_bytes"] += size

        for aid in app_ids:
            present = app_present.get(aid, {"blob_count": 0, "total_bytes": 0})
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
                        "avail", config.AVAIL_LN_INSTANCE, aid, h,
                        present["blob_count"], present["total_bytes"], None,
                        resp.latency_ms, True, None,
                        Json({"source": "header.app_lookup"}),
                    ),
                )
                inserted += 1
    print(f"[avail/app_id_mon] inserted {inserted} observations across {len(app_ids)} app_ids ({scan_start}..{scan_end})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
