"""Avail per-block availability re-check until settled.

Runs every minute. For each avail header not yet settled, calls /v2/blocks/{h}
and records the (status, confidence) sample. Settles when confidence reaches
the threshold or after MAX_ATTEMPTS retries.
"""
import sys
import traceback

from workers.common.db import cursor
from workers.common.rpc import AvailLC

MAX_PENDING_PER_RUN = 200
SETTLE_CONFIDENCE_THRESHOLD = 99.0
MAX_ATTEMPTS = 3


def get_pending(limit):
    with cursor() as cur:
        cur.execute(
            """
            SELECT ts, height,
                   COALESCE(availability_attempts, 0) AS attempts,
                   availability_max_confidence
            FROM headers
            WHERE da_layer = 'avail'
              AND availability_settled_at IS NULL
              AND COALESCE(availability_attempts, 0) < %s
            ORDER BY height
            LIMIT %s
            """,
            (MAX_ATTEMPTS, limit),
        )
        return cur.fetchall()


def main():
    pending = get_pending(MAX_PENDING_PER_RUN)
    if not pending:
        print("[avail/availability_check] no pending heights")
        return 0

    lc = AvailLC()
    settled = 0
    samples = 0
    for ts, height, attempts, max_conf in pending:
        resp = lc.get(f"/v2/blocks/{height}")
        attempt = attempts + 1
        if resp.success:
            r = resp.result or {}
            status = r.get("status")
            confidence = r.get("confidence")
            error_type = None
        else:
            status = None
            confidence = None
            error_type = resp.error_type

        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO block_availability_samples (
                    ts, da_layer, height, attempt, status, confidence,
                    available, latency_ms, error_type, details
                ) VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, NULL)
                """,
                (
                    "avail", height, attempt, status, confidence,
                    None, resp.latency_ms, error_type,
                ),
            )
            samples += 1

        new_max = max_conf if max_conf is not None else 0.0
        if confidence is not None:
            new_max = max(new_max, confidence)

        is_settled = False
        if confidence is not None and confidence >= SETTLE_CONFIDENCE_THRESHOLD:
            is_settled = True
        if attempt >= MAX_ATTEMPTS:
            is_settled = True

        with cursor() as cur:
            cur.execute(
                """
                UPDATE headers
                SET availability_first_check_at = COALESCE(availability_first_check_at, NOW()),
                    availability_attempts = %s,
                    availability_max_confidence = %s,
                    availability_last_confidence = %s,
                    availability_last_status = %s,
                    availability_settled_at = CASE WHEN %s THEN NOW() ELSE availability_settled_at END
                WHERE da_layer = 'avail' AND ts = %s AND height = %s
                """,
                (attempt, new_max, confidence, status, is_settled, ts, height),
            )

        if is_settled:
            settled += 1

    print(f"[avail/availability_check] samples={samples} settled={settled} of {len(pending)} pending")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
