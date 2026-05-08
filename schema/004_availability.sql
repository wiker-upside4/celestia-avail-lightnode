-- Per-block availability summary on headers + per-attempt samples hypertable.

ALTER TABLE headers ADD COLUMN IF NOT EXISTS availability_first_check_at TIMESTAMPTZ;
ALTER TABLE headers ADD COLUMN IF NOT EXISTS availability_settled_at TIMESTAMPTZ;
ALTER TABLE headers ADD COLUMN IF NOT EXISTS availability_attempts INT DEFAULT 0;
ALTER TABLE headers ADD COLUMN IF NOT EXISTS availability_max_confidence DOUBLE PRECISION;
ALTER TABLE headers ADD COLUMN IF NOT EXISTS availability_last_confidence DOUBLE PRECISION;
ALTER TABLE headers ADD COLUMN IF NOT EXISTS availability_last_status TEXT;

CREATE TABLE IF NOT EXISTS block_availability_samples (
    ts          TIMESTAMPTZ      NOT NULL,
    da_layer    TEXT             NOT NULL,
    height      BIGINT           NOT NULL,
    attempt     INT              NOT NULL,
    status      TEXT,
    confidence  DOUBLE PRECISION,
    available   BOOLEAN,
    latency_ms  INT,
    error_type  TEXT,
    details     JSONB
);
SELECT create_hypertable('block_availability_samples', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_avail_samples_height ON block_availability_samples (da_layer, height, ts DESC);
CREATE INDEX IF NOT EXISTS idx_avail_samples_layer_ts ON block_availability_samples (da_layer, ts DESC);
