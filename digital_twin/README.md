# digital_twin

Central Postgres database that merges telemetry from all 4 assembly modules, for the plant
simulation / digital twin program to read directly via its DB connector (ODBC/JDBC).

Every module keeps doing exactly what it already does — capturing, detecting, and publishing
telemetry to ThingsBoard. Nothing on the Pis changes. This adds exactly one new thing: a bridge
that copies each module's telemetry, as it arrives in ThingsBoard, into a clean, purpose-built
schema the simulation tool can query — instead of the simulation tool reading ThingsBoard's own
internal `ts_kv`/`ts_kv_latest` tables directly, which are a generic key-value time-series store
not meant for external consumption, and can change shape across ThingsBoard version upgrades.

```
[Module 1..4] --MQTT--> [ThingsBoard] --Rule Chain (REST API Call)--> [Node-RED bridge] --> [Postgres]
                                                                                                  ^
                                                                                                  |
                                                                                    [Simulation program, via ODBC/JDBC]
```

## 1. Set up the database

Create a Postgres database (can be on the same server as ThingsBoard, as its own separate
database — don't put this inside ThingsBoard's own database):

```bash
createdb digital_twin
psql -d digital_twin -f schema.sql
```

Then insert the 4 real modules once (adjust `module_id` to match the `machineID` values already
used in `FW_DOBOT/modularAssembly/order_data`, e.g. `module1`..`module4`):

```sql
INSERT INTO modules (module_id, name) VALUES
    ('module1', 'Module 1'),
    ('module2', 'Module 2'),
    ('module3', 'Module 3'),
    ('module4', 'Module 4');
```

## 2. ThingsBoard Rule Chain: forward telemetry to the bridge

This runs in the ThingsBoard UI (Rule Chains), not in this repo. For each device (or a shared
rule chain all 4 module devices route through):

1. After the existing "Save Timeseries" node (leave it in place — this doesn't replace your
   existing dashboard/telemetry storage, it just taps a copy of the same data), add a
   **Script** transformation node (Filter/Enrichment → Script) with this logic, so the outgoing
   payload always carries which module it came from, in the exact shape the bridge expects:

   ```javascript
   // ThingsBoard rule chain transformation script
   return {
       msg: {
           moduleId: metadata.deviceName,      // or hardcode per-device if deviceName doesn't match module_id
           components_count: msg.components_count
       },
       metadata: metadata,
       msgType: msgType
   };
   ```

   Adjust `metadata.deviceName` if your ThingsBoard device names don't already match the
   `module_id` values you inserted in step 1 (e.g. add a device attribute for `moduleId` instead
   and reference that).

2. Wire that Script node's output into a **REST API Call** node, configured with:
   - **Endpoint URL**: `http://<node-red-host>:1880/digital-twin/ingest`
   - **Request method**: `POST`

That's the whole ThingsBoard-side change — everything else in your existing rule chain (device
provisioning, alarms, dashboards, whatever else you have) stays untouched.

## 3. Node-RED bridge flow

Build this as a **new flow tab**, on whichever Node-RED instance is convenient to reach from
ThingsBoard (doesn't need to be on one of the 4 Pis — a central server, or even the same host
ThingsBoard runs on, is simplest).

**Prerequisite**: install a Postgres client node for Node-RED once, in that instance's user
directory (typically `~/.node-red`):

```bash
cd ~/.node-red
npm install node-red-contrib-postgres
```
(Check its exact node/config field names once installed — Node-RED Postgres packages vary
slightly by version; the flow below assumes a node that accepts a parameterized SQL query with
`$1`, `$2`, ... placeholders and takes `msg.payload` as the parameter array, which is the common
convention, but confirm against whatever version actually installs.)

**Flow shape**: `http in` → `function` (normalize) → two `postgres` nodes (counts, status) →
`http response`

- **`http in`**: Method `POST`, URL `/digital-twin/ingest`. Wire its output to the function node
  below.

- **`function` node** ("Normalize payload"), 2 outputs — paste this in:

  ```javascript
  // Input: { moduleId: "module1", components_count: { "trainEngine": {"red": 1}, ... } }
  const moduleId = msg.payload.moduleId;
  const counts = msg.payload.components_count || {};

  // Output 1: one row per (part_type, color) for the component_counts INSERT.
  // Each row is [module_id, part_type, color, count] matching the query's $1..$4.
  const rows = [];
  for (const partType of Object.keys(counts)) {
      for (const color of Object.keys(counts[partType])) {
          rows.push([moduleId, partType, color, counts[partType][color]]);
      }
  }

  // Output 2: a single upsert for module_status, marking this module as freshly seen.
  const statusMsg = { payload: [moduleId, 'online'] };

  // node-red-contrib-postgres (and similar) typically run one query per incoming msg, not
  // per array element - so split output 1 into one msg per row.
  const rowMsgs = rows.map(r => ({ payload: r }));

  return [rowMsgs, statusMsg];
  ```

  Wire output 1 (an array of messages — Node-RED's `function` node auto-splits an array-of-msgs
  output into separate sends) into the counts `postgres` node, and output 2 into the status
  `postgres` node.

- **`postgres` node (counts)** — query:
  ```sql
  INSERT INTO component_counts (module_id, part_type, color, count)
  VALUES ($1, $2, $3, $4)
  ```

- **`postgres` node (status)** — query:
  ```sql
  INSERT INTO module_status (module_id, status, last_seen_at)
  VALUES ($1, $2, now())
  ON CONFLICT (module_id) DO UPDATE SET status = EXCLUDED.status, last_seen_at = now()
  ```

- **`http response`** node: wire from both `postgres` nodes (or just one, if you want the HTTP
  response to only wait on the counts insert) back to an `http response` node so ThingsBoard's
  REST API Call node gets a clean `200 OK` instead of timing out waiting for a reply.

## 4. Test end-to-end, one module first

Before rolling this out to all 4 devices' rule chains, point just one module's rule chain at the
bridge, trigger a detection run from that module as usual, and confirm a row actually lands:

```sql
SELECT * FROM component_counts ORDER BY recorded_at DESC LIMIT 10;
SELECT * FROM module_status;
```

Once that's confirmed working, repeat the ThingsBoard Rule Chain change (step 2) for the
remaining 3 devices.

## Extending beyond aggregate counts

This first version only carries what every module already sends today — aggregate part/color
counts per detection run (`generate_component_counts()` in `YOLO/main.py`). If the simulation
needs richer per-detection data (pixel/robot coordinates, orientation, confidence, individual
assembly-order lifecycle events from `order_data`), that means: (1) publishing that additional
data to ThingsBoard from the modules too, (2) adding matching tables here, and (3) extending the
rule chain script + bridge flow to carry it through. Worth doing once you know exactly what the
simulation needs to query — no need to guess ahead of that.
