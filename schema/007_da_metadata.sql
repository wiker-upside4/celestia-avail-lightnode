-- DA layer metadata: claim vs measured 비교용 정책 정보.
-- 이 테이블은 dashboard에서 "공식 정책 X일 vs 실측 retrieval 성공률" 카드 만들 때 사용.

CREATE TABLE IF NOT EXISTS da_layer_metadata (
    da_layer                TEXT PRIMARY KEY,
    chain_decimals          INT,                  -- token 자릿수 (TIA=6, AVAIL=18, ETH=18)
    native_token            TEXT,                 -- 'TIA', 'AVAIL', 'ETH'
    block_time_seconds      NUMERIC,              -- 평균 블록 시간 (claim)
    retention_policy        TEXT,                 -- 'hard' (보장) / 'soft' (관행) / 'none'
    retention_days_claim    NUMERIC,              -- 공식 정책 일수 (NULL = no guarantee)
    retention_source_url    TEXT,                 -- 정책 출처 link
    finality_seconds_claim  NUMERIC,              -- 공식 finality 시간
    notes                   TEXT,
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- Seed: 4개 DA 레이어 (Celestia/Avail은 활성, EigenDA/Ethereum은 추후 워커 추가 시 채울 자리)
INSERT INTO da_layer_metadata (
    da_layer, chain_decimals, native_token,
    block_time_seconds, retention_policy, retention_days_claim,
    retention_source_url, finality_seconds_claim, notes
) VALUES
    ('celestia', 6, 'TIA',
     6, 'soft', NULL,
     'https://docs.celestia.org/concepts/data-availability-faq',
     6,
     'No hard retention guarantee. Pruning window and archive node practices commonly retain ~30 days. State sync from any full node afterward.'),
    ('avail', 18, 'AVAIL',
     20, 'soft', NULL,
     'https://docs.availproject.org/docs/learn-about-avail/lcs-and-clients',
     20,
     'Light client retention window depends on configuration. Full archive nodes retain indefinitely. Confirm exact policy via team channels.'),
    ('eigenda', 18, 'ETH',
     12, 'hard', 14,
     'https://docs.eigenlayer.xyz/eigenda/overview',
     720,
     'Documented 14-day retention via operator stake commitment. NOT YET MONITORED by DABEAT (worker stack TBD).'),
    ('ethereum', 18, 'ETH',
     12, 'hard', 18,
     'https://eips.ethereum.org/EIPS/eip-4844',
     780,
     'EIP-4844 blob retention 4096 epochs ≈ 18.2 days. Hard cliff. NOT YET MONITORED by DABEAT (worker stack TBD).')
ON CONFLICT (da_layer) DO UPDATE SET
    chain_decimals = EXCLUDED.chain_decimals,
    native_token = EXCLUDED.native_token,
    block_time_seconds = EXCLUDED.block_time_seconds,
    retention_policy = EXCLUDED.retention_policy,
    retention_days_claim = EXCLUDED.retention_days_claim,
    retention_source_url = EXCLUDED.retention_source_url,
    finality_seconds_claim = EXCLUDED.finality_seconds_claim,
    notes = EXCLUDED.notes,
    updated_at = NOW();

-- Read access for grafana
GRANT SELECT ON da_layer_metadata TO dabeat_ro;
