"""One-off backfill for headers rows missing data_size_bytes / block_hash.

Run: PYTHONPATH=/home/wiker/dabeat /home/wiker/.dabeat/venv/bin/python -m scripts.backfill

Idempotent: only touches rows where the target column is NULL.
"""
import sys

sys.path.insert(0, "/home/wiker/dabeat")
from workers.common.db import cursor
from workers.common.rpc import CelestiaRPC


def backfill_avail_data_size():
    with cursor() as cur:
        cur.execute(
            """
            UPDATE headers
            SET data_size_bytes = COALESCE(rows, 0) * COALESCE(cols, 0) * 32
            WHERE da_layer = 'avail' AND data_size_bytes IS NULL
            """
        )
        return cur.rowcount


def backfill_celestia_data_size():
    with cursor() as cur:
        cur.execute(
            """
            UPDATE headers
            SET data_size_bytes = square_size * square_size * 512
            WHERE da_layer = 'celestia' AND data_size_bytes IS NULL AND square_size IS NOT NULL
            """
        )
        return cur.rowcount


def backfill_celestia_block_hash():
    with cursor() as cur:
        cur.execute(
            """
            SELECT height FROM headers
            WHERE da_layer = 'celestia' AND block_hash IS NULL
            ORDER BY height
            """
        )
        heights = [r[0] for r in cur.fetchall()]

    if not heights:
        return 0

    rpc = CelestiaRPC()
    updated = 0
    for h in heights:
        resp = rpc.call("header.GetByHeight", [h])
        if not resp.success:
            sys.stderr.write(f"[backfill] GetByHeight({h}) failed: {resp.error_type}\n")
            continue
        commit = (resp.result or {}).get("commit") or {}
        block_hash = ((commit.get("block_id") or {}).get("hash"))
        if not block_hash:
            continue
        with cursor() as cur:
            cur.execute(
                """
                UPDATE headers
                SET block_hash = %s
                WHERE da_layer = 'celestia' AND height = %s AND block_hash IS NULL
                """,
                (block_hash, h),
            )
            updated += cur.rowcount
    return updated


if __name__ == "__main__":
    a = backfill_avail_data_size()
    c = backfill_celestia_data_size()
    b = backfill_celestia_block_hash()
    print(f"[backfill] avail data_size_bytes: {a} rows")
    print(f"[backfill] celestia data_size_bytes: {c} rows")
    print(f"[backfill] celestia block_hash: {b} rows")
