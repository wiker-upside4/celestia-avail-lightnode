"""Celestia self-probe submit worker. Cron every 1 minute.

Submits a small payload via blob.Submit to a fixed DABEAT namespace.
Records probe metadata + payload_hash + measured fee (balance diff) in `probes`.

Idempotent across cron firings: each run uses a fresh payload.
Failures recorded with submit_success=FALSE and classified error_type.
"""
import base64
import hashlib
import secrets
import sys
import time
import traceback

from workers.common import config
from workers.common.db import cursor, Json
from workers.common.rpc import CelestiaRPC

LN_INSTANCE = "celestia-A1"
# DABEAT namespace v0: 1 byte version (0x00) + 20 bytes pad + 8 bytes "DABEAT01"
NAMESPACE_HEX = "0000000000000000000000000000000000000000004441424541543031"
NAMESPACE_B64 = base64.standard_b64encode(bytes.fromhex(NAMESPACE_HEX)).decode()
GAS_PRICE = 0.002


def make_payload() -> tuple[bytes, str]:
    ts = int(time.time())
    nonce = secrets.token_hex(8)
    raw = f"dabeat-{ts}-{nonce}".encode()
    return raw, hashlib.sha256(raw).hexdigest()


def _balance(rpc: CelestiaRPC) -> int | None:
    r = rpc.call("state.Balance")
    if not r.success:
        return None
    try:
        return int(r.result.get("amount"))
    except (TypeError, ValueError):
        return None


def main():
    rpc = CelestiaRPC()
    raw, payload_hash = make_payload()
    payload_b64 = base64.standard_b64encode(raw).decode()

    # Pre-balance to compute fee_paid
    bal_before = _balance(rpc)

    blob_obj = {
        "namespace": NAMESPACE_B64,
        "data": payload_b64,
        "share_version": 0,
    }
    options = {"gas_price": GAS_PRICE}

    resp = rpc.call("blob.Submit", [[blob_obj], options])

    submit_success = False
    error_type = None
    height = None
    commitment = None
    details: dict = {"gas_price": GAS_PRICE, "share_version": 0}

    if resp.success:
        try:
            height = int(resp.result)
            submit_success = True
            details["height"] = height
        except (TypeError, ValueError):
            error_type = "bad_response"
            details["raw_result"] = str(resp.result)[:200]
    else:
        err_lower = (resp.error or "").lower()
        if "insufficient" in err_lower or "fund" in err_lower:
            error_type = "insufficient_funds"
        elif "out of gas" in err_lower or "out_of_gas" in err_lower:
            error_type = "out_of_gas"
        elif "deadline exceeded" in err_lower or "context deadline" in err_lower:
            error_type = "context_deadline"
        elif "namespace" in err_lower:
            error_type = "invalid_namespace"
        else:
            error_type = resp.error_type or "rpc_error"
        details["error"] = (resp.error or "")[:300]

    # Post-balance for fee measurement (only if submit succeeded)
    fee_paid = None
    if submit_success:
        # Wait briefly for state to update (LC syncs balance after block produces)
        time.sleep(15)
        bal_after = _balance(rpc)
        if bal_before is not None and bal_after is not None:
            fee_paid = bal_before - bal_after
            details["fee_paid_utia"] = fee_paid
            details["balance_before"] = bal_before
            details["balance_after"] = bal_after

    # Compute commitment from local lib (server returns blob inline only on retrieve)
    # blob.Submit response is just the height; commitment must be computed if we want
    # to record it. We'll fetch it on first retrieve instead.

    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO probes (
                da_layer, ln_instance, namespace_or_appid,
                payload_size_bytes, payload_hash,
                submit_height, submit_tx_hash, submit_latency_ms,
                submit_success, error_type, details
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING probe_id
            """,
            (
                "celestia", LN_INSTANCE, NAMESPACE_HEX,
                len(raw), payload_hash,
                height, None, resp.latency_ms,
                submit_success, error_type, Json(details) if details else None,
            ),
        )
        probe_id = cur.fetchone()[0]

    if submit_success:
        print(f"[celestia/submit] OK probe_id={probe_id} height={height} "
              f"latency={resp.latency_ms}ms fee={fee_paid} utia")
    else:
        print(f"[celestia/submit] FAIL probe_id={probe_id} error={error_type} "
              f"latency={resp.latency_ms}ms")
        sys.stderr.write(f"[celestia/submit] failed: {error_type} details={details}\n")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
