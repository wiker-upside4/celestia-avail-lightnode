-- Add per-block DA availability columns. Filled by celestia/shares_check worker.

ALTER TABLE headers ADD COLUMN IF NOT EXISTS shares_available BOOLEAN;
ALTER TABLE headers ADD COLUMN IF NOT EXISTS shares_check_latency_ms INT;
ALTER TABLE headers ADD COLUMN IF NOT EXISTS shares_check_error TEXT;
ALTER TABLE headers ADD COLUMN IF NOT EXISTS shares_checked_at TIMESTAMPTZ;
