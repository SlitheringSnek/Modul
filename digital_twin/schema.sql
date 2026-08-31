-- digital_twin/schema.sql
--
-- Central, purpose-built database that merges data from all 4 assembly modules for
-- consumption by the plant simulation / digital twin program. This is intentionally
-- separate from ThingsBoard's own internal telemetry tables (ts_kv/ts_kv_latest) - those
-- are a generic key-value time-series store, not meant for direct external querying, and
-- their shape can change across ThingsBoard versions. This schema is ours to keep stable.
--
-- Populated by a bridging Node-RED flow (see README.md, section 3) that receives telemetry
-- forwarded by a ThingsBoard Rule Chain whenever any module device reports new data.
--
-- Run once against a fresh database:
--   psql -U <user> -d <dbname> -f schema.sql

-- One row per physical module. Static reference data - insert the 4 real module_ids here
-- once (matching the "machineID" values already used in FW_DOBOT/modularAssembly/order_data,
-- e.g. 'module1'..'module4') before the bridge flow starts inserting into the other tables.
CREATE TABLE IF NOT EXISTS modules (
    module_id   TEXT PRIMARY KEY,
    name        TEXT,
    description TEXT
);

-- One row per (module, part_type, color) observation from a single detection run's
-- component_counts.json ("components_count" telemetry). Every run inserts fresh rows here
-- rather than updating in place, so this table is itself a time series - "what did each
-- module see, and when" - which is what a digital twin needs to reconstruct plant state
-- over time. Query MAX(recorded_at) per module for "current" counts.
CREATE TABLE IF NOT EXISTS component_counts (
    id          BIGSERIAL PRIMARY KEY,
    module_id   TEXT NOT NULL REFERENCES modules(module_id),
    part_type   TEXT NOT NULL,   -- e.g. 'trainEngine', 'trainCabin', 'trainBase'/'trainWheels'
    color       TEXT NOT NULL,   -- 'red' / 'green' / 'blue' / 'yellow'
    count       INTEGER NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_component_counts_module_time
    ON component_counts (module_id, recorded_at DESC);

-- Simple heartbeat / last-known-status per module, so the simulation can tell whether a
-- module is currently online without scanning the full time series. Upserted (not
-- inserted) by the bridge flow - one row per module_id, always current.
CREATE TABLE IF NOT EXISTS module_status (
    module_id    TEXT PRIMARY KEY REFERENCES modules(module_id),
    status       TEXT,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
