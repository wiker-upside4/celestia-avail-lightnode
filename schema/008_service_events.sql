-- Operational events: LC restarts, manual interventions, alerts, etc.
-- Logged by watchdog + future operational scripts. Useful for incident timeline.

CREATE TABLE IF NOT EXISTS service_events (
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type    TEXT        NOT NULL,
    target        TEXT,
    severity      TEXT,
    reason        TEXT,
    details       JSONB
);

SELECT create_hypertable('service_events', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_service_events_type_ts
    ON service_events (event_type, ts DESC);

GRANT SELECT ON service_events TO dabeat_ro;
