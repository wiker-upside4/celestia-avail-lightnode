"""Celestia header catch-up worker. Runs every minute via cron.

For each new block we insert one row into `headers` (block metadata) and one
row into `celestia_block_blobs` (network-wide blob aggregate computed by
parsing the EDS shares). The blob aggregate write is best-effort — a failed
share.GetEDS does not block the header insert.
"""
import sys
import traceback
from datetime import datetime, timezone

from workers.common.db import cursor, Json
from workers.common.rpc import CelestiaRPC
from workers.celestia.share_parser import count_blobs

MAX_BLOCKS_PER_RUN = 200


def _int(s, default=None):
    if s is None:
        return default
    try:
        return int(s)
    except (TypeError, ValueError):
        return default


def _parse_time(s):
    if not s:
        return None
    # Celestia returns RFC3339 with high-precision nanoseconds. Truncate to microsec.
    # Example: 2026-05-06T12:23:50.876795068Z
    s = s.replace("Z", "+00:00")
    if "." in s:
        prefix, rest = s.split(".", 1)
        # rest is 'NNNNNNNNN+00:00' — keep up to 6 digits of fraction
        if "+" in rest:
            frac, tz = rest.split("+", 1)
            frac = frac[:6]
            s = f"{prefix}.{frac}+{tz}"
        elif "-" in rest:
            frac, tz = rest.rsplit("-", 1)
            frac = frac[:6]
            s = f"{prefix}.{frac}-{tz}"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def get_last_height():
    with cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(height), 0) FROM headers WHERE da_layer = 'celestia'")
        return cur.fetchone()[0]


def _upsert_block_blobs(height, block_time, blob_count, total_bytes, ns_count):
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO celestia_block_blobs (
                height, block_time, blob_count, total_blob_bytes, namespace_count
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (height) DO UPDATE SET
                block_time       = EXCLUDED.block_time,
                blob_count       = EXCLUDED.blob_count,
                total_blob_bytes = EXCLUDED.total_blob_bytes,
                namespace_count  = EXCLUDED.namespace_count,
                collected_at     = NOW()
            """,
            (height, block_time, blob_count, total_bytes, ns_count),
        )


def _collect_block_blobs(rpc, height, block_time, eds_size):
    """Best-effort: fetch EDS, count blobs, upsert. Logs and swallows errors."""
    if not block_time or not eds_size:
        return
    if eds_size <= 0:
        # Empty block — no shares to fetch.
        _upsert_block_blobs(height, block_time, 0, 0, 0)
        return
    resp = rpc.call("share.GetEDS", [height])
    if not resp.success:
        sys.stderr.write(
            f"[celestia/header] GetEDS({height}) failed: {resp.error_type} — "
            f"block_blobs row skipped\n"
        )
        return
    shares = (resp.result or {}).get("data_square") or []
    if len(shares) != eds_size * eds_size:
        sys.stderr.write(
            f"[celestia/header] GetEDS({height}) returned {len(shares)} shares, "
            f"expected {eds_size*eds_size} — block_blobs row skipped\n"
        )
        return
    try:
        blob_count, total_bytes, ns_count = count_blobs(shares, eds_size)
    except Exception as e:
        sys.stderr.write(f"[celestia/header] share parse failed at h={height}: {e}\n")
        return
    _upsert_block_blobs(height, block_time, blob_count, total_bytes, ns_count)


def fetch_and_insert(start_height, end_height):
    rpc = CelestiaRPC()
    rows = []
    block_meta = []  # (height, block_time, eds_size) for block_blobs follow-up
    for h in range(start_height, end_height + 1):
        resp = rpc.call("header.GetByHeight", [h])
        if not resp.success:
            sys.stderr.write(f"[celestia/header] GetByHeight({h}) failed: {resp.error_type} {resp.error}\n")
            break
        result = resp.result
        header = result.get("header", {})
        commit = result.get("commit") or {}
        dah = result.get("dah") or {}
        row_roots = dah.get("row_roots") or []
        col_roots = dah.get("column_roots") or []
        block_hash = ((commit.get("block_id") or {}).get("hash"))
        square_size = len(row_roots)
        # Celestia share is 512 bytes; EDS = square_size^2 shares.
        eds_bytes = square_size * square_size * 512
        ods_bytes = (square_size // 2) * (square_size // 2) * 512
        block_time = _parse_time(header.get("time"))
        details = {
            "chain_id": header.get("chain_id"),
            "app_version": (header.get("version") or {}).get("app"),
            "ods_bytes": ods_bytes,
            "row_roots_count": len(row_roots),
            "column_roots_count": len(col_roots),
        }
        rows.append((
            "celestia",
            _int(header.get("height")),
            block_hash,
            block_time,
            (header.get("last_block_id") or {}).get("hash"),
            header.get("data_hash"),
            header.get("proposer_address"),
            square_size,
            None, None,
            eds_bytes,
            details,
        ))
        block_meta.append((_int(header.get("height")), block_time, square_size))

    if not rows:
        return 0

    with cursor() as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO headers (
                    ts, da_layer, height, block_hash, block_time, parent_hash,
                    data_root, proposer_address, square_size, rows, cols,
                    data_size_bytes, details
                ) VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (da_layer, height, ts) DO NOTHING
                """,
                (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10],
                 Json(r[11]) if r[11] else None),
            )

    # Phase 2: per-block blob aggregate (fail-safe per block).
    for height, block_time, sq in block_meta:
        if height is None:
            continue
        _collect_block_blobs(rpc, height, block_time, sq)

    return len(rows)


def main():
    rpc = CelestiaRPC()
    lh = rpc.call("header.LocalHead")
    if not lh.success:
        sys.stderr.write(f"[celestia/header] LocalHead failed: {lh.error_type}\n")
        return 1
    local_head = _int(lh.result["header"]["height"])
    last_db = get_last_height()
    if last_db == 0:
        # Bootstrap: start near the head to avoid huge backfill on first run
        start = max(local_head - 50, 1)
    else:
        start = last_db + 1
    end = min(local_head, start + MAX_BLOCKS_PER_RUN - 1)
    if start > local_head:
        return 0
    n = fetch_and_insert(start, end)
    print(f"[celestia/header] inserted {n} blocks ({start}..{end}, local_head={local_head})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
