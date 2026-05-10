"""Generate 5 DABEAT dashboards as Grafana JSON model.

Style notes:
- Grafana 13 schemaVersion 39
- Datasource uid: dabeat-pg
- 24-col grid; stat = 6x4, ts = 12x8 normally
- Color: celestia=purple, avail=teal
"""
import json
import os

OUT = os.path.join(os.path.dirname(__file__), "dashboards")
os.makedirs(OUT, exist_ok=True)

DS = {"type": "grafana-postgresql-datasource", "uid": "dabeat-pg"}
CELESTIA_COLOR = "purple"
AVAIL_COLOR = "blue"


def _next_id():
    _next_id.n = getattr(_next_id, "n", 0) + 1
    return _next_id.n


def _reset_id():
    _next_id.n = 0


def stat(title, sql, gp, unit="none", thresholds=None, color_mode="value"):
    p = {
        "id": _next_id(),
        "type": "stat",
        "title": title,
        "datasource": DS,
        "gridPos": gp,
        "targets": [{"datasource": DS, "rawSql": sql, "format": "table", "refId": "A", "editorMode": "code"}],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "thresholds": thresholds or {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
                "mappings": [],
            },
            "overrides": [],
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "auto",
            "textMode": "auto",
            "colorMode": color_mode,
            "graphMode": "none",
        },
    }
    return p


def timeseries(title, sql, gp, unit="none", legend="auto", overrides=None, thresholds_steps=None, custom_axis=None):
    p = {
        "id": _next_id(),
        "type": "timeseries",
        "title": title,
        "datasource": DS,
        "gridPos": gp,
        "targets": [{"datasource": DS, "rawSql": sql, "format": "time_series", "refId": "A", "editorMode": "code"}],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "linear",
                    "spanNulls": False,
                    "showPoints": "auto",
                    "pointSize": 4,
                    "fillOpacity": 10,
                    "axisLabel": custom_axis or "",
                },
                "thresholds": {"mode": "absolute", "steps": thresholds_steps or [{"color": "green", "value": None}]},
            },
            "overrides": overrides or [],
        },
        "options": {
            "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom", "calcs": []},
            "tooltip": {"mode": "multi", "sort": "none"},
        },
    }
    return p


def histogram(title, sql, gp, unit="none"):
    return {
        "id": _next_id(),
        "type": "histogram",
        "title": title,
        "datasource": DS,
        "gridPos": gp,
        "targets": [{"datasource": DS, "rawSql": sql, "format": "table", "refId": "A", "editorMode": "code"}],
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {"bucketSize": None, "combine": False},
    }


def gauge(title, sql, gp, unit="percent"):
    return {
        "id": _next_id(),
        "type": "gauge",
        "title": title,
        "datasource": DS,
        "gridPos": gp,
        "targets": [{"datasource": DS, "rawSql": sql, "format": "table", "refId": "A", "editorMode": "code"}],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "min": 0, "max": 100,
                "thresholds": {"mode": "absolute", "steps": [
                    {"color": "red", "value": None},
                    {"color": "yellow", "value": 80},
                    {"color": "green", "value": 95},
                ]},
            },
            "overrides": [],
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    }


def piechart(title, sql, gp):
    return {
        "id": _next_id(),
        "type": "piechart",
        "title": title,
        "datasource": DS,
        "gridPos": gp,
        "targets": [{"datasource": DS, "rawSql": sql, "format": "table", "refId": "A", "editorMode": "code"}],
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "pieType": "pie", "displayLabels": ["name", "percent"]},
    }


def barchart(title, sql, gp, unit="none"):
    return {
        "id": _next_id(),
        "type": "barchart",
        "title": title,
        "datasource": DS,
        "gridPos": gp,
        "targets": [{"datasource": DS, "rawSql": sql, "format": "table", "refId": "A", "editorMode": "code"}],
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {"orientation": "horizontal", "xTickLabelRotation": 0, "showValue": "auto"},
    }


def heatmap(title, sql, gp, unit="short"):
    return {
        "id": _next_id(),
        "type": "heatmap",
        "title": title,
        "datasource": DS,
        "gridPos": gp,
        "targets": [{"datasource": DS, "rawSql": sql, "format": "time_series", "refId": "A", "editorMode": "code"}],
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"scaleDistribution": {"type": "linear"}, "hideFrom": {"tooltip": False, "viz": False, "legend": False}}}},
        "options": {"calculate": False, "yAxis": {"axisPlacement": "left"}, "color": {"mode": "scheme", "scheme": "Spectral", "steps": 64}},
    }


def dashboard(uid, title, panels, refresh="1m", from_="now-6h"):
    return {
        "uid": uid,
        "title": title,
        "tags": ["dabeat"],
        "timezone": "browser",
        "refresh": refresh,
        "time": {"from": from_, "to": "now"},
        "panels": panels,
        "schemaVersion": 39,
        "version": 1,
        "editable": True,
        "graphTooltip": 0,
        "templating": {"list": []},
        "annotations": {"list": []},
    }


def write_dashboard(name, d):
    path = os.path.join(OUT, name)
    with open(path, "w") as f:
        json.dump(d, f, indent=2)
    print(f"wrote {path}")


# =====================================================================
# DASHBOARD 1: Overview
# =====================================================================
_reset_id()
panels = []

# Row 1: 4 stat panels
panels.append(stat(
    "Celestia Latest Height",
    "SELECT network_head FROM node_health WHERE da_layer='celestia' AND network_head IS NOT NULL ORDER BY ts DESC LIMIT 1",
    {"x": 0, "y": 0, "w": 6, "h": 4}, "none",
))
panels.append(stat(
    "Avail Latest Height",
    "SELECT network_head FROM node_health WHERE da_layer='avail' AND network_head IS NOT NULL ORDER BY ts DESC LIMIT 1",
    {"x": 6, "y": 0, "w": 6, "h": 4}, "none",
))
panels.append(stat(
    "Total Blocks (Celestia)",
    "SELECT COUNT(*) FROM headers WHERE da_layer='celestia'",
    {"x": 12, "y": 0, "w": 6, "h": 4}, "none",
))
panels.append(stat(
    "Total Blocks (Avail)",
    "SELECT COUNT(*) FROM headers WHERE da_layer='avail'",
    {"x": 18, "y": 0, "w": 6, "h": 4}, "none",
))

# Row 2: 4 stat panels with thresholds
panels.append(stat(
    "Celestia Sync Lag",
    "SELECT sync_lag FROM node_health WHERE da_layer='celestia' ORDER BY ts DESC LIMIT 1",
    {"x": 0, "y": 4, "w": 6, "h": 4}, "short",
    thresholds={"mode": "absolute", "steps": [
        {"color": "green", "value": None},
        {"color": "yellow", "value": 10},
        {"color": "red", "value": 100},
    ]},
    color_mode="background",
))
panels.append(stat(
    "Avail Sync Lag",
    "SELECT sync_lag FROM node_health WHERE da_layer='avail' ORDER BY ts DESC LIMIT 1",
    {"x": 6, "y": 4, "w": 6, "h": 4}, "short",
    thresholds={"mode": "absolute", "steps": [
        {"color": "green", "value": None},
        {"color": "yellow", "value": 10},
        {"color": "red", "value": 100},
    ]},
    color_mode="background",
))
panels.append(stat(
    "Celestia Peers",
    "SELECT peers_count FROM node_health WHERE da_layer='celestia' AND peers_count IS NOT NULL ORDER BY ts DESC LIMIT 1",
    {"x": 12, "y": 4, "w": 6, "h": 4}, "short",
    thresholds={"mode": "absolute", "steps": [
        {"color": "red", "value": None},
        {"color": "yellow", "value": 5},
        {"color": "green", "value": 15},
    ]},
    color_mode="background",
))
panels.append(stat(
    "Avail Confidence (latest)",
    "SELECT block_confidence FROM node_health WHERE da_layer='avail' AND block_confidence IS NOT NULL ORDER BY ts DESC LIMIT 1",
    {"x": 18, "y": 4, "w": 6, "h": 4}, "percent",
    thresholds={"mode": "absolute", "steps": [
        {"color": "red", "value": None},
        {"color": "yellow", "value": 80},
        {"color": "green", "value": 95},
    ]},
    color_mode="background",
))

# Row 3: RPC Health
panels.append(timeseries(
    "RPC Latency (ms)",
    """SELECT time_bucket('1 minute', ts) AS time,
              da_layer AS metric,
              AVG(rpc_latency_ms) AS value
       FROM node_health WHERE $__timeFilter(ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 8, "w": 12, "h": 8}, "ms",
))

# RPC Success Rate
panels.append(timeseries(
    "RPC Success Rate (%)",
    """SELECT time_bucket('5 minute', ts) AS time,
              da_layer AS metric,
              100.0 * COUNT(*) FILTER (WHERE rpc_success) / NULLIF(COUNT(*), 0) AS value
       FROM node_health WHERE $__timeFilter(ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 12, "y": 8, "w": 12, "h": 8}, "percent",
))

# Block production rate
panels.append(timeseries(
    "Block Production Rate (blocks/min)",
    """SELECT time_bucket('1 minute', ts) AS time,
              da_layer AS metric,
              COUNT(*) AS value
       FROM headers WHERE $__timeFilter(ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 16, "w": 24, "h": 8}, "short",
))

write_dashboard("01_overview.json", dashboard("dabeat-overview", "DABEAT — Overview", panels))


# =====================================================================
# DASHBOARD 2: Node Health
# =====================================================================
_reset_id()
panels = []

panels.append(timeseries(
    "Sync Lag (blocks)",
    """SELECT time_bucket('1 minute', ts) AS time,
              da_layer AS metric,
              MAX(sync_lag) AS value
       FROM node_health WHERE $__timeFilter(ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 0, "w": 24, "h": 8}, "short",
    thresholds_steps=[
        {"color": "green", "value": None},
        {"color": "yellow", "value": 10},
        {"color": "red", "value": 100},
    ],
))

panels.append(timeseries(
    "Celestia Peer Count",
    """SELECT time_bucket('1 minute', ts) AS time,
              'peers' AS metric, AVG(peers_count) AS value
       FROM node_health WHERE da_layer='celestia' AND peers_count IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1 ORDER BY 1""",
    {"x": 0, "y": 8, "w": 12, "h": 8}, "short",
    thresholds_steps=[
        {"color": "red", "value": None},
        {"color": "yellow", "value": 5},
        {"color": "green", "value": 15},
    ],
))

panels.append(timeseries(
    "Celestia Bandwidth Rate (KB/s)",
    """SELECT time_bucket('1 minute', ts) AS time,
              'rate_in' AS metric, AVG(rate_in)/1024.0 AS value
       FROM node_health WHERE da_layer='celestia' AND $__timeFilter(ts)
       GROUP BY 1
       UNION ALL
       SELECT time_bucket('1 minute', ts) AS time,
              'rate_out' AS metric, AVG(rate_out)/1024.0 AS value
       FROM node_health WHERE da_layer='celestia' AND $__timeFilter(ts)
       GROUP BY 1
       ORDER BY 1""",
    {"x": 12, "y": 8, "w": 12, "h": 8}, "KBs",
))

panels.append(timeseries(
    "Celestia Cumulative Bandwidth (GB)",
    """SELECT ts AS time,
              'in_total' AS metric, bandwidth_in_total/1073741824.0 AS value
       FROM node_health WHERE da_layer='celestia' AND $__timeFilter(ts)
       UNION ALL
       SELECT ts AS time,
              'out_total' AS metric, bandwidth_out_total/1073741824.0 AS value
       FROM node_health WHERE da_layer='celestia' AND $__timeFilter(ts)
       ORDER BY 1""",
    {"x": 0, "y": 16, "w": 12, "h": 8}, "decgbytes",
))

panels.append(timeseries(
    "Celestia DAS Concurrency",
    """SELECT time_bucket('1 minute', ts) AS time,
              'concurrency' AS metric, MAX(das_concurrency) AS value
       FROM node_health WHERE da_layer='celestia' AND $__timeFilter(ts)
       GROUP BY 1 ORDER BY 1""",
    {"x": 12, "y": 16, "w": 12, "h": 8}, "short",
))

panels.append(timeseries(
    "Avail Block Confidence (%)",
    """SELECT time_bucket('1 minute', ts) AS time,
              'confidence' AS metric, AVG(block_confidence) AS value
       FROM node_health WHERE da_layer='avail' AND block_confidence IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1 ORDER BY 1""",
    {"x": 0, "y": 24, "w": 12, "h": 8}, "percent",
    thresholds_steps=[
        {"color": "red", "value": None},
        {"color": "yellow", "value": 80},
        {"color": "green", "value": 95},
    ],
))

panels.append(timeseries(
    "RPC Latency Percentiles (ms)",
    """SELECT time_bucket('5 minute', ts) AS time,
              da_layer || '_p50' AS metric,
              percentile_cont(0.5) WITHIN GROUP (ORDER BY rpc_latency_ms) AS value
       FROM node_health WHERE rpc_latency_ms IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1, da_layer
       UNION ALL
       SELECT time_bucket('5 minute', ts) AS time,
              da_layer || '_p95' AS metric,
              percentile_cont(0.95) WITHIN GROUP (ORDER BY rpc_latency_ms) AS value
       FROM node_health WHERE rpc_latency_ms IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1, da_layer
       UNION ALL
       SELECT time_bucket('5 minute', ts) AS time,
              da_layer || '_p99' AS metric,
              percentile_cont(0.99) WITHIN GROUP (ORDER BY rpc_latency_ms) AS value
       FROM node_health WHERE rpc_latency_ms IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1, da_layer
       ORDER BY 1""",
    {"x": 12, "y": 24, "w": 12, "h": 8}, "ms",
))

write_dashboard("02_node_health.json", dashboard("dabeat-health", "DABEAT — Node Health", panels))


# =====================================================================
# DASHBOARD 3: Block Production
# =====================================================================
_reset_id()
panels = []

panels.append(timeseries(
    "Block Time (s)",
    """WITH t AS (
         SELECT da_layer, height, block_time,
                LAG(block_time) OVER (PARTITION BY da_layer ORDER BY height) AS prev_t
         FROM headers WHERE block_time IS NOT NULL AND $__timeFilter(ts)
       )
       SELECT time_bucket('5 minute', block_time) AS time,
              da_layer AS metric,
              AVG(EXTRACT(EPOCH FROM (block_time - prev_t))) AS value
       FROM t WHERE prev_t IS NOT NULL
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 0, "w": 24, "h": 8}, "s",
))

panels.append(timeseries(
    "Celestia Square Size",
    """SELECT time_bucket('5 minute', ts) AS time,
              'square_size' AS metric, AVG(square_size)::int AS value
       FROM headers WHERE da_layer='celestia' AND square_size IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1 ORDER BY 1""",
    {"x": 0, "y": 8, "w": 12, "h": 8}, "short",
))

panels.append(timeseries(
    "Avail Matrix Cells (rows*cols)",
    """SELECT time_bucket('5 minute', ts) AS time,
              'cells' AS metric, AVG(rows*cols)::int AS value
       FROM headers WHERE da_layer='avail' AND rows IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1 ORDER BY 1""",
    {"x": 12, "y": 8, "w": 12, "h": 8}, "short",
))

panels.append(timeseries(
    "Data Size per Block (KB)",
    """SELECT time_bucket('5 minute', ts) AS time,
              da_layer AS metric, AVG(data_size_bytes)/1024.0 AS value
       FROM headers WHERE data_size_bytes IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 16, "w": 12, "h": 8}, "deckbytes",
))

panels.append(timeseries(
    "Throughput (KB/s, 5m bucket)",
    """SELECT time_bucket('5 minute', ts) AS time,
              da_layer AS metric,
              SUM(data_size_bytes)/1024.0/300.0 AS value
       FROM headers WHERE data_size_bytes IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 12, "y": 16, "w": 12, "h": 8}, "KBs",
))

panels.append(histogram(
    "Block Time Distribution (s) — Celestia",
    """WITH t AS (
         SELECT height, block_time,
                LAG(block_time) OVER (ORDER BY height) AS prev_t
         FROM headers WHERE da_layer='celestia' AND block_time IS NOT NULL AND $__timeFilter(ts)
       )
       SELECT EXTRACT(EPOCH FROM (block_time - prev_t)) AS block_time_s
       FROM t WHERE prev_t IS NOT NULL""",
    {"x": 0, "y": 24, "w": 12, "h": 8}, "s",
))
panels.append(histogram(
    "Block Time Distribution (s) — Avail",
    """WITH t AS (
         SELECT height, block_time,
                LAG(block_time) OVER (ORDER BY height) AS prev_t
         FROM headers WHERE da_layer='avail' AND block_time IS NOT NULL AND $__timeFilter(ts)
       )
       SELECT EXTRACT(EPOCH FROM (block_time - prev_t)) AS block_time_s
       FROM t WHERE prev_t IS NOT NULL""",
    {"x": 12, "y": 24, "w": 12, "h": 8}, "s",
))

write_dashboard("03_block_production.json", dashboard("dabeat-blocks", "DABEAT — Block Production", panels))


# =====================================================================
# DASHBOARD 4: Availability
# =====================================================================
_reset_id()
panels = []

panels.append(timeseries(
    "Sampling Success Rate (%, 5m bucket)",
    """SELECT time_bucket('5 minute', ts) AS time,
              'celestia' AS metric,
              100.0 * COUNT(*) FILTER (WHERE available) / NULLIF(COUNT(*), 0) AS value
       FROM block_availability_samples WHERE da_layer='celestia' AND $__timeFilter(ts)
       GROUP BY 1
       UNION ALL
       SELECT time_bucket('5 minute', ts) AS time,
              'avail' AS metric,
              100.0 * COUNT(*) FILTER (WHERE confidence >= 92) / NULLIF(COUNT(*), 0) AS value
       FROM block_availability_samples WHERE da_layer='avail' AND $__timeFilter(ts)
       GROUP BY 1
       ORDER BY 1""",
    {"x": 0, "y": 0, "w": 24, "h": 8}, "percent",
    thresholds_steps=[
        {"color": "red", "value": None},
        {"color": "yellow", "value": 80},
        {"color": "green", "value": 95},
    ],
))

panels.append(histogram(
    "Avail Confidence Distribution",
    """SELECT confidence FROM block_availability_samples
       WHERE da_layer='avail' AND confidence IS NOT NULL AND $__timeFilter(ts)""",
    {"x": 0, "y": 8, "w": 12, "h": 8}, "percent",
))

panels.append(timeseries(
    "Sampling Latency p50/p95 (ms)",
    """SELECT time_bucket('5 minute', ts) AS time,
              da_layer || '_p50' AS metric,
              percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS value
       FROM block_availability_samples WHERE latency_ms IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1, da_layer
       UNION ALL
       SELECT time_bucket('5 minute', ts) AS time,
              da_layer || '_p95' AS metric,
              percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS value
       FROM block_availability_samples WHERE latency_ms IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1, da_layer
       ORDER BY 1""",
    {"x": 12, "y": 8, "w": 12, "h": 8}, "ms",
))

panels.append(piechart(
    "Avail Sampling Status Breakdown",
    """SELECT status AS metric, COUNT(*) AS value
       FROM block_availability_samples
       WHERE da_layer='avail' AND status IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1""",
    {"x": 0, "y": 16, "w": 12, "h": 8},
))

panels.append(gauge(
    "Block Coverage — Celestia (last 1h)",
    """WITH measured AS (
         SELECT COUNT(DISTINCT height) AS m FROM block_availability_samples
         WHERE da_layer='celestia' AND ts > NOW() - INTERVAL '1 hour'
       ), produced AS (
         SELECT COUNT(*) AS p FROM headers
         WHERE da_layer='celestia' AND ts > NOW() - INTERVAL '1 hour'
       )
       SELECT 100.0 * (SELECT m FROM measured) / NULLIF((SELECT p FROM produced), 0) AS pct""",
    {"x": 12, "y": 16, "w": 6, "h": 8},
))
panels.append(gauge(
    "Block Coverage — Avail (last 1h)",
    """WITH measured AS (
         SELECT COUNT(DISTINCT height) AS m FROM block_availability_samples
         WHERE da_layer='avail' AND ts > NOW() - INTERVAL '1 hour'
       ), produced AS (
         SELECT COUNT(*) AS p FROM headers
         WHERE da_layer='avail' AND ts > NOW() - INTERVAL '1 hour'
       )
       SELECT 100.0 * (SELECT m FROM measured) / NULLIF((SELECT p FROM produced), 0) AS pct""",
    {"x": 18, "y": 16, "w": 6, "h": 8},
))

# Pseudo survival: success rate vs block age
panels.append(timeseries(
    "Pseudo Survival: success rate vs block age (s)",
    """SELECT EXTRACT(EPOCH FROM (s.ts - h.block_time))::int AS time,
              s.da_layer AS metric,
              CASE WHEN s.da_layer='celestia' THEN
                100.0 * COUNT(*) FILTER (WHERE s.available) / NULLIF(COUNT(*),0)
              ELSE
                100.0 * COUNT(*) FILTER (WHERE s.confidence >= 92) / NULLIF(COUNT(*),0)
              END AS value
       FROM block_availability_samples s
       JOIN headers h ON h.da_layer=s.da_layer AND h.height=s.height
       WHERE h.block_time IS NOT NULL AND $__timeFilter(s.ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 24, "w": 24, "h": 8}, "percent",
))

write_dashboard("04_availability.json", dashboard("dabeat-availability", "DABEAT — Availability", panels))


# =====================================================================
# DASHBOARD 5: Namespace Activity
# =====================================================================
_reset_id()
panels = []

panels.append(heatmap(
    "Avail Activity Heatmap (blob_count by app_id, 1h bucket)",
    """SELECT time_bucket('1 hour', no.ts) AS time,
              COALESCE(mn.rollup_name, no.namespace_or_appid) AS metric,
              SUM(no.blob_count) AS value
       FROM namespace_observations no
       LEFT JOIN monitored_namespaces mn ON mn.da_layer=no.da_layer AND mn.namespace_or_appid=no.namespace_or_appid
       WHERE no.da_layer='avail' AND $__timeFilter(no.ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 0, "w": 24, "h": 8},
))

panels.append(timeseries(
    "Avail Total Bytes per Namespace (5m bucket)",
    """SELECT time_bucket('5 minute', no.ts) AS time,
              COALESCE(mn.rollup_name, no.namespace_or_appid) AS metric,
              SUM(no.total_bytes) AS value
       FROM namespace_observations no
       LEFT JOIN monitored_namespaces mn ON mn.da_layer=no.da_layer AND mn.namespace_or_appid=no.namespace_or_appid
       WHERE no.da_layer='avail' AND $__timeFilter(no.ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 8, "w": 12, "h": 8}, "bytes",
))

panels.append(timeseries(
    "Avail Avg Blob Count / Block by Namespace",
    """SELECT time_bucket('5 minute', no.ts) AS time,
              COALESCE(mn.rollup_name, no.namespace_or_appid) AS metric,
              AVG(no.blob_count) AS value
       FROM namespace_observations no
       LEFT JOIN monitored_namespaces mn ON mn.da_layer=no.da_layer AND mn.namespace_or_appid=no.namespace_or_appid
       WHERE no.da_layer='avail' AND $__timeFilter(no.ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 12, "y": 8, "w": 12, "h": 8}, "short",
))

panels.append(timeseries(
    "Fetch Success Rate per Namespace (Avail, 5m)",
    """SELECT time_bucket('5 minute', no.ts) AS time,
              COALESCE(mn.rollup_name, no.namespace_or_appid) AS metric,
              100.0 * COUNT(*) FILTER (WHERE no.fetch_success) / NULLIF(COUNT(*),0) AS value
       FROM namespace_observations no
       LEFT JOIN monitored_namespaces mn ON mn.da_layer=no.da_layer AND mn.namespace_or_appid=no.namespace_or_appid
       WHERE no.da_layer='avail' AND $__timeFilter(no.ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 16, "w": 12, "h": 8}, "percent",
))

panels.append(barchart(
    "Top Active Namespaces (24h, Avail)",
    """SELECT COALESCE(mn.rollup_name, no.namespace_or_appid) AS namespace,
              SUM(no.blob_count) AS blobs,
              SUM(no.total_bytes) AS bytes
       FROM namespace_observations no
       LEFT JOIN monitored_namespaces mn ON mn.da_layer=no.da_layer AND mn.namespace_or_appid=no.namespace_or_appid
       WHERE no.da_layer='avail' AND no.ts > NOW() - INTERVAL '24 hours'
       GROUP BY 1 ORDER BY blobs DESC LIMIT 10""",
    {"x": 12, "y": 16, "w": 12, "h": 8}, "short",
))

panels.append(timeseries(
    "Avail Activity by Hour of Day (UTC)",
    """SELECT date_trunc('hour', no.ts) AS time,
              EXTRACT(HOUR FROM no.ts)::text AS metric,
              SUM(no.blob_count) AS value
       FROM namespace_observations no
       WHERE no.da_layer='avail' AND $__timeFilter(no.ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 24, "w": 24, "h": 8}, "short",
))

# ── Celestia namespace section (rows 32~) ─────────────────────────────────
panels.append(heatmap(
    "Celestia Activity Heatmap (blob_count by namespace, 1h bucket)",
    """SELECT time_bucket('1 hour', no.ts) AS time,
              COALESCE(mn.rollup_name, LEFT(no.namespace_or_appid, 16)) AS metric,
              SUM(no.blob_count) AS value
       FROM namespace_observations no
       LEFT JOIN monitored_namespaces mn USING (da_layer, namespace_or_appid)
       WHERE no.da_layer='celestia' AND $__timeFilter(no.ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 32, "w": 24, "h": 8},
))

panels.append(timeseries(
    "Celestia Total Bytes per Namespace (5m bucket)",
    """SELECT time_bucket('5 minute', no.ts) AS time,
              COALESCE(mn.rollup_name, LEFT(no.namespace_or_appid, 16)) AS metric,
              SUM(no.total_bytes) AS value
       FROM namespace_observations no
       LEFT JOIN monitored_namespaces mn USING (da_layer, namespace_or_appid)
       WHERE no.da_layer='celestia' AND $__timeFilter(no.ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 40, "w": 12, "h": 8}, "bytes",
))

panels.append(barchart(
    "Celestia Top Active Namespaces (24h)",
    """SELECT COALESCE(mn.rollup_name, LEFT(no.namespace_or_appid, 16)) AS namespace,
              SUM(no.blob_count) AS blobs,
              SUM(no.total_bytes) AS bytes
       FROM namespace_observations no
       LEFT JOIN monitored_namespaces mn USING (da_layer, namespace_or_appid)
       WHERE no.da_layer='celestia' AND no.ts > NOW() - INTERVAL '24 hours'
       GROUP BY 1 ORDER BY blobs DESC LIMIT 10""",
    {"x": 12, "y": 40, "w": 12, "h": 8}, "short",
))

panels.append(timeseries(
    "Celestia Fetch Success Rate per Namespace (5m)",
    """SELECT time_bucket('5 minute', no.ts) AS time,
              COALESCE(mn.rollup_name, LEFT(no.namespace_or_appid, 16)) AS metric,
              100.0 * COUNT(*) FILTER (WHERE no.fetch_success) / NULLIF(COUNT(*),0) AS value
       FROM namespace_observations no
       LEFT JOIN monitored_namespaces mn USING (da_layer, namespace_or_appid)
       WHERE no.da_layer='celestia' AND $__timeFilter(no.ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 48, "w": 24, "h": 8}, "percent",
))

write_dashboard("05_namespace.json", dashboard("dabeat-namespace", "DABEAT — Namespace Activity", panels))


# =====================================================================
# DASHBOARD 6: Self-Probe & Fraud (Avail + Celestia)
# =====================================================================
_reset_id()
panels = []

# Row 1: KPI stats
panels.append(stat(
    "Avail Submits (last 1h)",
    "SELECT COUNT(*) FROM probes WHERE da_layer='avail' AND submit_success AND ts > NOW() - INTERVAL '1 hour'",
    {"x": 0, "y": 0, "w": 6, "h": 4}, "short",
))
panels.append(stat(
    "Celestia Submits (last 1h)",
    "SELECT COUNT(*) FROM probes WHERE da_layer='celestia' AND submit_success AND ts > NOW() - INTERVAL '1 hour'",
    {"x": 6, "y": 0, "w": 6, "h": 4}, "short",
))
panels.append(stat(
    "Fraud Events (Celestia, all-time)",
    "SELECT COUNT(*) FROM fraud_events",
    {"x": 12, "y": 0, "w": 6, "h": 4}, "short",
    thresholds={"mode": "absolute", "steps": [
        {"color": "green", "value": None},
        {"color": "yellow", "value": 1},
        {"color": "red", "value": 5},
    ]},
    color_mode="background",
))
panels.append(stat(
    "In-flight Avail probes (settle 대기)",
    """SELECT COUNT(*) FROM headers
       WHERE da_layer='avail' AND availability_settled_at IS NULL
         AND availability_attempts > 0""",
    {"x": 18, "y": 0, "w": 6, "h": 4}, "short",
))

# Row 2: Submit time series
panels.append(timeseries(
    "Submit Rate (per 5min bucket)",
    """SELECT time_bucket('5 minute', ts) AS time,
              da_layer AS metric,
              COUNT(*) AS value
       FROM probes WHERE submit_success AND $__timeFilter(ts)
       GROUP BY 1, 2 ORDER BY 1""",
    {"x": 0, "y": 4, "w": 12, "h": 8}, "short",
))

panels.append(timeseries(
    "Submit Latency p50/p95 (ms)",
    """SELECT time_bucket('5 minute', ts) AS time,
              da_layer || '_p50' AS metric,
              percentile_cont(0.5) WITHIN GROUP (ORDER BY submit_latency_ms) AS value
       FROM probes WHERE submit_success AND $__timeFilter(ts)
       GROUP BY 1, da_layer
       UNION ALL
       SELECT time_bucket('5 minute', ts) AS time,
              da_layer || '_p95' AS metric,
              percentile_cont(0.95) WITHIN GROUP (ORDER BY submit_latency_ms) AS value
       FROM probes WHERE submit_success AND $__timeFilter(ts)
       GROUP BY 1, da_layer
       ORDER BY 1""",
    {"x": 12, "y": 4, "w": 12, "h": 8}, "ms",
))

# Row 3: Survival Curve — bucket × layer
panels.append(timeseries(
    "Retrieval Success Rate by Bucket (Survival Curve)",
    """SELECT time_bucket('15 minute', ts) AS time,
              da_layer || '_' || bucket_label AS metric,
              100.0 * COUNT(*) FILTER (WHERE fetch_success) / NULLIF(COUNT(*), 0) AS value
       FROM retrievals WHERE $__timeFilter(ts)
       GROUP BY 1, da_layer, bucket_label ORDER BY 1""",
    {"x": 0, "y": 12, "w": 24, "h": 8}, "percent",
    thresholds_steps=[
        {"color": "red", "value": None},
        {"color": "yellow", "value": 80},
        {"color": "green", "value": 95},
    ],
))

# Row 4: Retrieval latency
panels.append(timeseries(
    "Retrieval Latency p50/p95 by Layer (ms)",
    """SELECT time_bucket('5 minute', ts) AS time,
              da_layer || '_p50' AS metric,
              percentile_cont(0.5) WITHIN GROUP (ORDER BY fetch_latency_ms) AS value
       FROM retrievals WHERE fetch_latency_ms IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1, da_layer
       UNION ALL
       SELECT time_bucket('5 minute', ts) AS time,
              da_layer || '_p95' AS metric,
              percentile_cont(0.95) WITHIN GROUP (ORDER BY fetch_latency_ms) AS value
       FROM retrievals WHERE fetch_latency_ms IS NOT NULL AND $__timeFilter(ts)
       GROUP BY 1, da_layer
       ORDER BY 1""",
    {"x": 0, "y": 20, "w": 12, "h": 8}, "ms",
))

panels.append(timeseries(
    "Retrieval bucket별 success rate (current)",
    """SELECT date_trunc('hour', ts) AS time,
              da_layer || '_' || bucket_label AS metric,
              100.0 * COUNT(*) FILTER (WHERE fetch_success) / NULLIF(COUNT(*), 0) AS value
       FROM retrievals
       WHERE $__timeFilter(ts)
       GROUP BY 1, da_layer, bucket_label
       ORDER BY 1""",
    {"x": 12, "y": 20, "w": 12, "h": 8}, "percent",
))

# Row 5: Worker freshness + Celestia fee tracking
panels.append(barchart(
    "Worker Freshness (각 테이블 마지막 INSERT — minutes ago)",
    """SELECT t AS worker_table, EXTRACT(EPOCH FROM (NOW() - last_insert))/60 AS minutes_ago FROM (
       SELECT 'node_health' AS t, MAX(ts) AS last_insert FROM node_health
       UNION ALL SELECT 'headers',                MAX(ts) FROM headers
       UNION ALL SELECT 'block_avail_samples',    MAX(ts) FROM block_availability_samples
       UNION ALL SELECT 'namespace_obs',          MAX(ts) FROM namespace_observations
       UNION ALL SELECT 'probes',                 MAX(ts) FROM probes
       UNION ALL SELECT 'retrievals',             MAX(ts) FROM retrievals
       ) x ORDER BY minutes_ago DESC""",
    {"x": 0, "y": 28, "w": 12, "h": 8}, "m",
))

panels.append(timeseries(
    "Celestia fee (utia/submit)",
    """SELECT ts AS time,
              'celestia_utia' AS metric,
              (details->>'fee_paid_utia')::int AS value
       FROM probes
       WHERE da_layer='celestia' AND submit_success
         AND details->>'fee_paid_utia' IS NOT NULL
         AND $__timeFilter(ts)
       ORDER BY 1""",
    {"x": 12, "y": 28, "w": 6, "h": 8}, "short",
))

panels.append(timeseries(
    "Avail fee (mAVAIL/submit, 1e-3 AVAIL)",
    """SELECT ts AS time,
              'avail_mavail' AS metric,
              (details->>'fee_paid_avail')::numeric * 1000 AS value
       FROM probes
       WHERE da_layer='avail' AND submit_success
         AND details->>'fee_paid_avail' IS NOT NULL
         AND $__timeFilter(ts)
       ORDER BY 1""",
    {"x": 18, "y": 28, "w": 6, "h": 8}, "short",
))

write_dashboard("06_self_probe_fraud.json", dashboard("dabeat-probes", "DABEAT — Self-Probe & Fraud", panels))


# =====================================================================
# DASHBOARD 7: DA Comparison (L2Beat-style overview, 팀 요구안 공통 레이어 5 메트릭)
# =====================================================================
_reset_id()
panels = []

# Row 1: Liveness ── DA 한 카드씩 (Avail / Celestia 큰 숫자)
panels.append(stat(
    "Avail Liveness (24h submit success rate)",
    """SELECT
         ROUND(100.0 * COUNT(*) FILTER (WHERE submit_success) / NULLIF(COUNT(*), 0), 2) AS pct
       FROM probes WHERE da_layer='avail' AND ts > NOW() - INTERVAL '24 hours'""",
    {"x": 0, "y": 0, "w": 6, "h": 5}, "percent",
    thresholds={"mode": "absolute", "steps": [
        {"color": "red", "value": None},
        {"color": "yellow", "value": 95},
        {"color": "green", "value": 99},
    ]},
    color_mode="background",
))
panels.append(stat(
    "Celestia Liveness (24h submit success rate)",
    """SELECT
         ROUND(100.0 * COUNT(*) FILTER (WHERE submit_success) / NULLIF(COUNT(*), 0), 2) AS pct
       FROM probes WHERE da_layer='celestia' AND ts > NOW() - INTERVAL '24 hours'""",
    {"x": 6, "y": 0, "w": 6, "h": 5}, "percent",
    thresholds={"mode": "absolute", "steps": [
        {"color": "red", "value": None},
        {"color": "yellow", "value": 95},
        {"color": "green", "value": 99},
    ]},
    color_mode="background",
))

# Row 1 cont: Retrieval Health (5m bucket headline)
panels.append(stat(
    "Avail Retrieval Health (5m bucket, 24h)",
    """SELECT
         ROUND(100.0 * COUNT(*) FILTER (WHERE fetch_success) / NULLIF(COUNT(*), 0), 2) AS pct
       FROM retrievals WHERE da_layer='avail' AND bucket_label='5m'
         AND ts > NOW() - INTERVAL '24 hours'""",
    {"x": 12, "y": 0, "w": 6, "h": 5}, "percent",
    thresholds={"mode": "absolute", "steps": [
        {"color": "red", "value": None},
        {"color": "yellow", "value": 95},
        {"color": "green", "value": 99},
    ]},
    color_mode="background",
))
panels.append(stat(
    "Celestia Retrieval Health (5m bucket, 24h)",
    """SELECT
         ROUND(100.0 * COUNT(*) FILTER (WHERE fetch_success) / NULLIF(COUNT(*), 0), 2) AS pct
       FROM retrievals WHERE da_layer='celestia' AND bucket_label='5m'
         AND ts > NOW() - INTERVAL '24 hours'""",
    {"x": 18, "y": 0, "w": 6, "h": 5}, "percent",
    thresholds={"mode": "absolute", "steps": [
        {"color": "red", "value": None},
        {"color": "yellow", "value": 95},
        {"color": "green", "value": 99},
    ]},
    color_mode="background",
))

# Row 2: Finality / Confirmation time
panels.append(stat(
    "Avail Finality p50 (s)",
    """SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY submit_latency_ms) / 1000.0
       FROM probes WHERE da_layer='avail' AND submit_success
         AND ts > NOW() - INTERVAL '24 hours'""",
    {"x": 0, "y": 5, "w": 6, "h": 4}, "s",
))
panels.append(stat(
    "Celestia Finality p50 (s)",
    """SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY submit_latency_ms) / 1000.0
       FROM probes WHERE da_layer='celestia' AND submit_success
         AND ts > NOW() - INTERVAL '24 hours'""",
    {"x": 6, "y": 5, "w": 6, "h": 4}, "s",
))

# Row 2 cont: Cost per submit
panels.append(stat(
    "Avail Cost per submit (mAVAIL)",
    """SELECT ROUND(AVG((details->>'fee_paid_avail')::numeric * 1000)::numeric, 2)
       FROM probes WHERE da_layer='avail' AND submit_success
         AND details->>'fee_paid_avail' IS NOT NULL
         AND ts > NOW() - INTERVAL '24 hours'""",
    {"x": 12, "y": 5, "w": 6, "h": 4}, "short",
))
panels.append(stat(
    "Celestia Cost per submit (utia)",
    """SELECT ROUND(AVG((details->>'fee_paid_utia')::int)::numeric, 1)
       FROM probes WHERE da_layer='celestia' AND submit_success
         AND details->>'fee_paid_utia' IS NOT NULL
         AND ts > NOW() - INTERVAL '24 hours'""",
    {"x": 18, "y": 5, "w": 6, "h": 4}, "short",
))

# Row 3: Retention — claim vs measured
panels.append({
    "id": _next_id(),
    "type": "table",
    "title": "Retention: Claim vs Measured",
    "datasource": DS,
    "gridPos": {"x": 0, "y": 9, "w": 24, "h": 8},
    "targets": [{
        "datasource": DS,
        "rawSql": """
            SELECT
              m.da_layer AS "DA",
              m.native_token AS "Token",
              m.retention_policy AS "Policy",
              m.retention_days_claim AS "Claim (days)",
              ROUND(EXTRACT(EPOCH FROM (NOW() - MIN(p.ts))) / 86400.0, 1) AS "Measured Span (days)",
              COALESCE(
                ROUND(100.0 * COUNT(r.*) FILTER (WHERE r.fetch_success) / NULLIF(COUNT(r.*), 0), 2),
                NULL
              ) AS "All-Bucket Retrieval %",
              m.notes AS "Notes"
            FROM da_layer_metadata m
            LEFT JOIN probes p ON p.da_layer = m.da_layer AND p.submit_success
            LEFT JOIN retrievals r ON r.probe_id = p.probe_id
            GROUP BY m.da_layer, m.native_token, m.retention_policy, m.retention_days_claim, m.notes
            ORDER BY m.da_layer
        """,
        "format": "table",
        "refId": "A",
        "editorMode": "code",
    }],
    "fieldConfig": {"defaults": {"unit": "none"}, "overrides": []},
    "options": {"showHeader": True},
})

# Row 4: Survival Curve (시간 지나도 데이터 살아있나)
panels.append(timeseries(
    "Survival Curve — bucket × layer (24h)",
    """SELECT date_trunc('hour', ts) AS time,
              da_layer || '_' || bucket_label AS metric,
              100.0 * COUNT(*) FILTER (WHERE fetch_success) / NULLIF(COUNT(*), 0) AS value
       FROM retrievals WHERE $__timeFilter(ts)
       GROUP BY 1, da_layer, bucket_label
       ORDER BY 1""",
    {"x": 0, "y": 17, "w": 24, "h": 8}, "percent",
    thresholds_steps=[
        {"color": "red", "value": None},
        {"color": "yellow", "value": 80},
        {"color": "green", "value": 95},
    ],
))

# Row 5: Cost trend (USD-comparable proxy)
panels.append(timeseries(
    "Avail Cost Trend (mAVAIL/submit, 5m avg)",
    """SELECT time_bucket('5 min', ts) AS time,
              'avail' AS metric,
              AVG((details->>'fee_paid_avail')::numeric * 1000) AS value
       FROM probes WHERE da_layer='avail' AND submit_success
         AND details->>'fee_paid_avail' IS NOT NULL
         AND $__timeFilter(ts)
       GROUP BY 1 ORDER BY 1""",
    {"x": 0, "y": 25, "w": 12, "h": 8}, "short",
))
panels.append(timeseries(
    "Celestia Cost Trend (utia/submit, 5m avg)",
    """SELECT time_bucket('5 min', ts) AS time,
              'celestia' AS metric,
              AVG((details->>'fee_paid_utia')::int)::int AS value
       FROM probes WHERE da_layer='celestia' AND submit_success
         AND details->>'fee_paid_utia' IS NOT NULL
         AND $__timeFilter(ts)
       GROUP BY 1 ORDER BY 1""",
    {"x": 12, "y": 25, "w": 12, "h": 8}, "short",
))

write_dashboard("07_da_comparison.json", dashboard("dabeat-comparison", "DABEAT — DA Comparison", panels))

print("\nAll 7 dashboards written.")

