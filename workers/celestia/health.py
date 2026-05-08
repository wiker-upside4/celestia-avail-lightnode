"""Celestia light node health worker. Runs every minute via cron."""
import json
import sys
import traceback
from datetime import datetime, timezone

from workers.common import config
from workers.common.db import cursor, Json
from workers.common.rpc import CelestiaRPC


def _int(s, default=None):
    if s is None:
        return default
    try:
        return int(s)
    except (TypeError, ValueError):
        return default


def collect():
    rpc = CelestiaRPC()
    latencies = []
    rpc_success = True
    details = {}

    network_head = local_head = sampled_head = None
    sync_lag = None
    is_syncing = None
    das_running = das_concurrency = das_failed_samples = None
    peers_count = None
    bw_in = bw_out = rate_in = rate_out = None

    nh = rpc.call("header.NetworkHead")
    latencies.append(nh.latency_ms)
    if nh.success:
        network_head = _int(nh.result["header"]["height"])
    else:
        rpc_success = False
        details["NetworkHead_error"] = nh.error_type

    lh = rpc.call("header.LocalHead")
    latencies.append(lh.latency_ms)
    if lh.success:
        local_head = _int(lh.result["header"]["height"])
    else:
        rpc_success = False
        details["LocalHead_error"] = lh.error_type

    if network_head is not None and local_head is not None:
        sync_lag = network_head - local_head
        is_syncing = sync_lag > 1

    ds = rpc.call("das.SamplingStats")
    latencies.append(ds.latency_ms)
    if ds.success:
        r = ds.result
        sampled_head = _int(r.get("head_of_sampled_chain"))
        das_concurrency = _int(r.get("concurrency"))
        das_running = bool(r.get("is_running"))
        details["catch_up_done"] = r.get("catch_up_done")
        details["head_of_catchup"] = r.get("head_of_catchup")
    else:
        details["SamplingStats_error"] = ds.error_type

    pp = rpc.call("p2p.Peers")
    latencies.append(pp.latency_ms)
    if pp.success and isinstance(pp.result, list):
        peers_count = len(pp.result)
    else:
        details["Peers_error"] = pp.error_type

    pb = rpc.call("p2p.BandwidthStats")
    latencies.append(pb.latency_ms)
    if pb.success:
        r = pb.result
        bw_in = _int(r.get("TotalIn"))
        bw_out = _int(r.get("TotalOut"))
        rate_in = _int(r.get("RateIn"))
        rate_out = _int(r.get("RateOut"))
    else:
        details["BandwidthStats_error"] = pb.error_type

    ni = rpc.call("node.Info")
    if ni.success:
        details["node_info"] = ni.result

    ss = rpc.call("header.SyncState")
    if ss.success:
        details["sync_state"] = ss.result

    rs = rpc.call("p2p.ResourceState")
    if rs.success and isinstance(rs.result, dict):
        sysr = rs.result.get("System") or {}
        details["resource_state"] = {
            "streams_in": sysr.get("NumStreamsInbound"),
            "streams_out": sysr.get("NumStreamsOutbound"),
            "conns_in": sysr.get("NumConnsInbound"),
            "conns_out": sysr.get("NumConnsOutbound"),
            "fd": sysr.get("NumFD"),
            "memory_bytes": sysr.get("Memory"),
        }

    nat = rpc.call("p2p.NATStatus")
    if nat.success:
        # 0=Unknown, 1=Public, 2=Private (libp2p reachability codes)
        details["nat_status"] = nat.result

    # gossipsub peers on the celestia header pubsub topic — proxy for healthy data dissemination
    psp = rpc.call("p2p.PubSubPeers", [""])
    if psp.success and isinstance(psp.result, list):
        details["pubsub_peers_count"] = len(psp.result)

    rpc_latency_ms = max(latencies) if latencies else None

    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO node_health (
                ts, da_layer, ln_instance,
                network_head, local_head, sampled_head, sync_lag, is_syncing,
                das_running, das_concurrency, das_failed_samples,
                peers_count, bandwidth_in_total, bandwidth_out_total, rate_in, rate_out,
                rpc_latency_ms, rpc_success, details
            ) VALUES (
                NOW(), %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s
            )
            """,
            (
                "celestia", config.CELESTIA_LN_INSTANCE,
                network_head, local_head, sampled_head, sync_lag, is_syncing,
                das_running, das_concurrency, das_failed_samples,
                peers_count, bw_in, bw_out, rate_in, rate_out,
                rpc_latency_ms, rpc_success, Json(details) if details else None,
            ),
        )


if __name__ == "__main__":
    try:
        collect()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
