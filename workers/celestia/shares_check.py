"""Celestia per-block DA availability check via share.SharesAvailable.

Every minute via cron: pick celestia headers with shares_available IS NULL
(oldest first), call share.SharesAvailable(height), store the result.
Single-shot — does not re-check already-checked blocks.
"""
import sys
import traceback

from workers.common.db import cursor
from workers.common.rpc import CelestiaRPC

MAX_BLOCKS_PER_RUN = 100


def get_pending_heights(limit):
    with cursor() as cur:
        cur.execute(
            """
            SELECT ts, height FROM headers
            WHERE da_layer = 'celestia' AND shares_available IS NULL
            ORDER BY height
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def main():
    pending = get_pending_heights(MAX_BLOCKS_PER_RUN)
    if not pending:
        print("[celestia/shares_check] no pending heights")
        return 0

    rpc = CelestiaRPC()
    checked = 0
    available = 0
    for ts, h in pending:
        resp = rpc.call("share.SharesAvailable", [h])
        if resp.success:
            ok, err = True, None
            available += 1
        else:
            ok = False
            err = (resp.error_type or "") + ":" + (resp.error or "")
            err = err[:500]
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO block_availability_samples (
                    ts, da_layer, height, attempt, status, confidence,
                    available, latency_ms, error_type, details
                ) VALUES (NOW(), %s, %s, 1, NULL, NULL, %s, %s, %s, NULL)
                """,
                ("celestia", h, ok, resp.latency_ms, resp.error_type if not ok else None),
            )
            cur.execute(
                """
                UPDATE headers
                SET shares_available = %s,
                    shares_check_latency_ms = %s,
                    shares_check_error = %s,
                    shares_checked_at = NOW(),
                    availability_first_check_at = COALESCE(availability_first_check_at, NOW()),
                    availability_settled_at = NOW(),
                    availability_attempts = 1
                WHERE da_layer = 'celestia' AND ts = %s AND height = %s
                """,
                (ok, resp.latency_ms, err, ts, h),
            )
        checked += 1
    print(f"[celestia/shares_check] checked {checked} (available={available})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
