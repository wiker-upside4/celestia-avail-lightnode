-- Fraud proof events. Most days this table is empty — entries indicate
-- something went wrong on the DA layer.

CREATE TABLE IF NOT EXISTS fraud_events (
    ts             TIMESTAMPTZ NOT NULL,
    da_layer       TEXT        NOT NULL,
    ln_instance    TEXT        NOT NULL,
    proof_type     TEXT        NOT NULL,
    block_height   BIGINT,
    raw_proof      JSONB,
    details        JSONB
);
SELECT create_hypertable('fraud_events', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_fraud_events_layer_type ON fraud_events (da_layer, proof_type, ts DESC);
CREATE INDEX IF NOT EXISTS idx_fraud_events_height ON fraud_events (da_layer, block_height);
