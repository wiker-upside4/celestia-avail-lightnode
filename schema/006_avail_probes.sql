-- Avail self-probe support: payload_hash for matching, bucket_label for retrieval cadence

ALTER TABLE probes ADD COLUMN IF NOT EXISTS payload_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_probes_layer_appid_hash
  ON probes (da_layer, namespace_or_appid, payload_hash);

ALTER TABLE retrievals ADD COLUMN IF NOT EXISTS bucket_label TEXT;
CREATE INDEX IF NOT EXISTS idx_retrievals_probe_bucket
  ON retrievals (probe_id, bucket_label);
