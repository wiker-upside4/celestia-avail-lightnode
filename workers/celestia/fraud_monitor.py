"""Celestia fraud proof monitor.

Calls fraud.Get for each known proof type every minute via cron.
- "datastore: key not found" → normal (no fraud detected)
- success with non-empty result → fraud detected, INSERT into fraud_events

fraud.Subscribe is the streaming alternative but requires WebSocket which
this HTTP-only worker can't use. Polling at 1-min granularity is acceptable
since fraud events are extremely rare and delay tolerance is high.

Currently celestia-node v0.30.x officially supports only one proof type:
bad-encoding (BEFP). Add more here when Celestia ships them.
"""
import sys
import traceback

from workers.common import config
from workers.common.db import cursor, Json
from workers.common.rpc import CelestiaRPC

KNOWN_PROOF_TYPES = ["bad-encoding"]


def _looks_like_no_fraud(err_msg: str) -> bool:
    """Identify the 'no fraud detected' error from a true RPC failure."""
    if not err_msg:
        return False
    s = err_msg.lower()
    return "key not found" in s or "datastore" in s or "not found" in s


def _extract_height(proof) -> int | None:
    """Best-effort: pull a block height out of various proof shapes."""
    if not isinstance(proof, dict):
        return None
    for key in ("BlockHeight", "block_height", "Height", "height"):
        v = proof.get(key)
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                pass
    return None


def main():
    rpc = CelestiaRPC()
    detected = 0
    for ptype in KNOWN_PROOF_TYPES:
        resp = rpc.call("fraud.Get", [ptype])

        if not resp.success:
            if _looks_like_no_fraud(resp.error):
                continue  # normal — no fraud of this type
            sys.stderr.write(
                f"[celestia/fraud_monitor] {ptype}: unexpected error: "
                f"{resp.error_type} {resp.error[:200]}\n"
            )
            continue

        # Success → result is either a single proof or a list of proofs
        result = resp.result
        proofs = result if isinstance(result, list) else [result] if result else []
        if not proofs:
            continue

        for proof in proofs:
            height = _extract_height(proof)
            with cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO fraud_events (
                        ts, da_layer, ln_instance, proof_type,
                        block_height, raw_proof, details
                    ) VALUES (NOW(), %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        "celestia",
                        config.CELESTIA_LN_INSTANCE,
                        ptype,
                        height,
                        Json(proof),
                        Json({"detection_latency_ms": resp.latency_ms}),
                    ),
                )
            detected += 1

    if detected:
        # Make this loud — fraud is a serious signal
        print(f"[celestia/fraud_monitor] !!! DETECTED {detected} fraud proof(s) !!!")
        sys.stderr.write(
            f"[celestia/fraud_monitor] !!! DETECTED {detected} fraud proof(s) — "
            f"check fraud_events table !!!\n"
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
