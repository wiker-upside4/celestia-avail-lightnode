-- Network-wide per-block blob aggregates. One row per (da_layer, height).
-- Populated by celestia/header and avail/header workers as part of their
-- normal catch-up loop — no new RPC connections introduced.

CREATE TABLE IF NOT EXISTS celestia_block_blobs (
    height            BIGINT PRIMARY KEY,
    block_time        TIMESTAMPTZ NOT NULL,
    blob_count        INTEGER NOT NULL,
    total_blob_bytes  BIGINT,
    namespace_count   INTEGER,
    collected_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_celestia_block_blobs_time
    ON celestia_block_blobs (block_time DESC);

CREATE TABLE IF NOT EXISTS avail_block_blobs (
    height            BIGINT PRIMARY KEY,
    block_time        TIMESTAMPTZ NOT NULL,
    blob_count        INTEGER NOT NULL,
    total_blob_bytes  BIGINT,
    app_id_count      INTEGER,
    collected_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_avail_block_blobs_time
    ON avail_block_blobs (block_time DESC);

GRANT SELECT ON celestia_block_blobs TO dabeat_ro;
GRANT SELECT ON avail_block_blobs TO dabeat_ro;
