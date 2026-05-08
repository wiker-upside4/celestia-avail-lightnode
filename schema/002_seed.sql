-- DABEAT seed data for monitored_namespaces

-- Celestia: well-known rollups. Namespace hex values are PLACEHOLDERS — must be
-- replaced with real 29-byte (v0: 0x00 + 28-byte id) namespace hex values from
-- celenium.io before flipping active=TRUE.
INSERT INTO monitored_namespaces (da_layer, namespace_or_appid, rollup_name, source, active) VALUES
    ('celestia', 'PLACEHOLDER_manta_pacific',  'Manta Pacific',  'manual', FALSE),
    ('celestia', 'PLACEHOLDER_eclipse',        'Eclipse',        'manual', FALSE),
    ('celestia', 'PLACEHOLDER_movement',       'Movement',       'manual', FALSE),
    ('celestia', 'PLACEHOLDER_lightlink',      'Lightlink',      'manual', FALSE),
    ('celestia', 'PLACEHOLDER_aevo',           'Aevo',           'manual', FALSE)
ON CONFLICT (da_layer, namespace_or_appid) DO NOTHING;

-- Avail: well-known app_ids. Numeric IDs are real — rollup_name unknown, marked
-- so user can fill in. Marked active=TRUE since the IDs themselves are valid.
INSERT INTO monitored_namespaces (da_layer, namespace_or_appid, rollup_name, source, active) VALUES
    ('avail', '1',  'unknown', 'avail-explorer', TRUE),
    ('avail', '7',  'unknown', 'avail-explorer', TRUE),
    ('avail', '11', 'unknown', 'avail-explorer', TRUE)
ON CONFLICT (da_layer, namespace_or_appid) DO NOTHING;
