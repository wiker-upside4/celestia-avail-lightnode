"""Avail header catch-up worker. Runs every minute via cron.

Pulls /v2/blocks/{n}/header for new blocks since last DB max(height).
Stays within the LC's available range to avoid 404s.

For each new block we insert one row into `headers` (block metadata) and one
row into `avail_block_blobs` (network-wide blob aggregate computed from the
same header's extension.app_lookup — no extra RPC call). The block_time used
matches headers.block_time (LC `received_at`, ≈chain time within a few sec).
"""
import sys
import traceback
from datetime import datetime, timezone

from workers.common.db import cursor, Json
from workers.common.rpc import AvailLC

MAX_BLOCKS_PER_RUN = 100


def get_last_height():
    with cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(height), 0) FROM headers WHERE da_layer = 'avail'")
        return cur.fetchone()[0]


def _upsert_block_blobs(height, block_time, blob_count, total_bytes, app_id_count):
    if block_time is None:
        # block_blobs.block_time is NOT NULL — skip rather than fail the row.
        return
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO avail_block_blobs (
                height, block_time, blob_count, total_blob_bytes, app_id_count
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (height) DO UPDATE SET
                block_time       = EXCLUDED.block_time,
                blob_count       = EXCLUDED.blob_count,
                total_blob_bytes = EXCLUDED.total_blob_bytes,
                app_id_count     = EXCLUDED.app_id_count,
                collected_at     = NOW()
            """,
            (height, block_time, blob_count, total_bytes, app_id_count),
        )


def _aggregate_app_lookup(app_lookup):
    """Return (blob_count, total_blob_bytes, app_id_count) from a block header's
    extension.app_lookup. `index` lists every blob slot in the block across all
    app_ids; `size` is the total app-data byte count.
    """
    index = (app_lookup or {}).get("index") or []
    total_size = (app_lookup or {}).get("size") or 0
    blob_count = len(index)
    app_ids = {e.get("appId") for e in index if e.get("appId") is not None}
    return blob_count, int(total_size), len(app_ids)


def main():
    lc = AvailLC()
    st = lc.get("/v2/status")
    if not st.success:
        sys.stderr.write(f"[avail/header] status failed: {st.error_type}\n")
        return 1
    avail = (st.result.get("blocks") or {}).get("available") or {}
    first_avail = avail.get("first")
    last_avail = avail.get("last")
    if first_avail is None or last_avail is None:
        print("[avail/header] no available blocks yet")
        return 0

    last_db = get_last_height()
    if last_db == 0:
        start = max(last_avail - 50, first_avail)
    else:
        start = max(last_db + 1, first_avail)
    end = min(last_avail, start + MAX_BLOCKS_PER_RUN - 1)
    if start > last_avail:
        return 0

    inserted = 0
    consecutive_failures = 0
    for h in range(start, end + 1):
        resp = lc.get(f"/v2/blocks/{h}/header")
        if not resp.success:
            sys.stderr.write(f"[avail/header] block {h} header failed: {resp.error_type}\n")
            if resp.error_type in ("not_found",):
                continue  # skip missing block, try next
            consecutive_failures += 1
            if consecutive_failures >= 3:
                break  # sustained issue (timeout/connection), stop hammering
            continue
        consecutive_failures = 0
        d = resp.result
        ext = d.get("extension") or {}
        block_time = None
        ra = d.get("received_at")
        if isinstance(ra, (int, float)):
            block_time = datetime.fromtimestamp(int(ra), tz=timezone.utc)
        commitments = ext.get("commitments") or []
        rows_n = ext.get("rows") or 0
        cols_n = ext.get("cols") or 0
        # Avail cell = 32 bytes; rows*cols cells span the full erasure-coded matrix.
        block_total_bytes = rows_n * cols_n * 32
        app_lookup = ext.get("app_lookup") or {}
        app_data_cells = app_lookup.get("size") or 0
        details = {
            "extrinsics_root": d.get("extrinsics_root"),
            "state_root": d.get("state_root"),
            "app_lookup": app_lookup,
            "app_data_bytes": app_data_cells * 32,
            "kzg_commitments": commitments,
        }
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO headers (
                    ts, da_layer, height, block_hash, block_time, parent_hash,
                    data_root, proposer_address, square_size, rows, cols,
                    data_size_bytes, details
                ) VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (da_layer, height, ts) DO NOTHING
                """,
                (
                    "avail", d.get("number"), d.get("hash"), block_time,
                    d.get("parent_hash"), ext.get("data_root"), None,
                    None, rows_n, cols_n,
                    block_total_bytes, Json(details),
                ),
            )

        # Network-wide blob aggregate from the same header response — no extra RPC.
        try:
            blob_count, total_bytes, app_id_count = _aggregate_app_lookup(app_lookup)
            _upsert_block_blobs(d.get("number"), block_time, blob_count, total_bytes, app_id_count)
        except Exception as e:
            sys.stderr.write(f"[avail/header] block_blobs upsert failed h={h}: {e}\n")

        inserted += 1
    print(f"[avail/header] inserted {inserted} blocks ({start}..{end}, last_avail={last_avail})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
