-- DABEAT initial schema (TimescaleDB)

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- node_health: time series of light node health metrics
CREATE TABLE IF NOT EXISTS node_health (
    ts                    TIMESTAMPTZ NOT NULL,
    da_layer              TEXT        NOT NULL,
    ln_instance           TEXT        NOT NULL,
    network_head          BIGINT,
    local_head            BIGINT,
    sampled_head          BIGINT,
    sync_lag              INT,
    is_syncing            BOOLEAN,
    das_running           BOOLEAN,
    das_concurrency       INT,
    das_failed_samples    INT,
    block_confidence      DOUBLE PRECISION,
    peers_count           INT,
    bandwidth_in_total    BIGINT,
    bandwidth_out_total   BIGINT,
    rate_in               BIGINT,
    rate_out              BIGINT,
    rpc_latency_ms        INT,
    rpc_success           BOOLEAN     NOT NULL,
    details               JSONB
);
SELECT create_hypertable('node_health', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_node_health_layer_ts ON node_health (da_layer, ts DESC);

-- headers: time series of block headers
CREATE TABLE IF NOT EXISTS headers (
    ts                  TIMESTAMPTZ NOT NULL,
    da_layer            TEXT        NOT NULL,
    height              BIGINT      NOT NULL,
    block_hash          TEXT,
    block_time          TIMESTAMPTZ,
    parent_hash         TEXT,
    data_root           TEXT,
    proposer_address    TEXT,
    square_size         INT,
    rows                INT,
    cols                INT,
    data_size_bytes     BIGINT,
    details             JSONB,
    UNIQUE (da_layer, height, ts)
);
SELECT create_hypertable('headers', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_headers_layer_height ON headers (da_layer, height DESC);

-- namespace_observations: per-namespace/app_id activity time series
CREATE TABLE IF NOT EXISTS namespace_observations (
    ts                   TIMESTAMPTZ NOT NULL,
    da_layer             TEXT        NOT NULL,
    ln_instance          TEXT        NOT NULL,
    namespace_or_appid   TEXT        NOT NULL,
    height               BIGINT      NOT NULL,
    blob_count           INT,
    total_bytes          BIGINT,
    commitments          TEXT[],
    fetch_latency_ms     INT,
    fetch_success        BOOLEAN,
    error_type           TEXT,
    details              JSONB,
    UNIQUE (da_layer, namespace_or_appid, height, ts)
);
SELECT create_hypertable('namespace_observations', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_nsobs_layer_ns_ts ON namespace_observations (da_layer, namespace_or_appid, ts DESC);
CREATE INDEX IF NOT EXISTS idx_nsobs_layer_height ON namespace_observations (da_layer, height);

-- monitored_namespaces: configuration table (regular)
CREATE TABLE IF NOT EXISTS monitored_namespaces (
    da_layer             TEXT NOT NULL,
    namespace_or_appid   TEXT NOT NULL,
    rollup_name          TEXT,
    source               TEXT,
    added_at             TIMESTAMPTZ DEFAULT NOW(),
    active               BOOLEAN     DEFAULT TRUE,
    PRIMARY KEY (da_layer, namespace_or_appid)
);

-- probes: self-probe submission record (regular, used after token funding)
CREATE TABLE IF NOT EXISTS probes (
    probe_id             BIGSERIAL PRIMARY KEY,
    ts                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    da_layer             TEXT NOT NULL,
    ln_instance          TEXT NOT NULL,
    namespace_or_appid   TEXT,
    payload_size_bytes   INT,
    submit_height        BIGINT,
    submit_tx_hash       TEXT,
    submit_latency_ms    INT,
    submit_success       BOOLEAN,
    error_type           TEXT,
    details              JSONB
);
CREATE INDEX IF NOT EXISTS idx_probes_layer_ts ON probes (da_layer, ts DESC);

-- retrievals: self-probe retrieval results (hypertable, used after token funding)
CREATE TABLE IF NOT EXISTS retrievals (
    ts                   TIMESTAMPTZ NOT NULL,
    probe_id             BIGINT      NOT NULL,
    da_layer             TEXT        NOT NULL,
    ln_instance          TEXT        NOT NULL,
    attempt              INT         NOT NULL,
    fetch_latency_ms     INT,
    fetch_success        BOOLEAN,
    bytes_received       BIGINT,
    error_type           TEXT,
    details              JSONB
);
SELECT create_hypertable('retrievals', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_retrievals_probe ON retrievals (probe_id, ts DESC);
