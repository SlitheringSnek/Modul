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

This runs in the ThingsBoard UI (Rule Chains), not in this repo. In this project's actual
ThingsBoard instance, every device (the 4 module devices, plus unrelated ones like the AGV) shares
one Root Rule Chain - so this is a **one-time change**, not something repeated per module. Three
things are important, discovered by checking a real device's actual data rather than assuming:

- **`components_count` is sent as a Shared Attribute update ("Post attributes"), not telemetry
  ("Post telemetry")** - confirmed by checking a real device's "Shared attributes" tab (had a fresh
  `components_count` value) versus its "Latest telemetry" tab (completely empty). This means the
  filter/script/REST-call chain below must hang off the **"Save Shared Attributes"** node, *not*
  "Save Timeseries" as originally assumed - wiring it after Save Timeseries silently never fires,
  with no error anywhere, since that branch never carries this data at all.
- **Device names aren't `module1`..`module4`** - the actual ThingsBoard device names are
  `NodeRed #1`..`NodeRed #4`. The Script node below maps them explicitly; update the mapping if
  your device names differ or change.
- **Other devices' shared-attribute updates pass through the same "Save Shared Attributes" node**
  (`Zalogovnik_Dobot`, `AGV`, etc.), which don't have `components_count` at all - a **filter**
  before the Script node keeps those from being forwarded (and failing) at all.

After the existing "Save Shared Attributes" node (leave it in place — this doesn't replace your
existing dashboard/attribute storage, it just taps a copy of the same data):

1. Add a **Check fields presence** filter node, configured to check that `components_count` is
   present. Wire "Save Shared Attributes" → this node (label the link "Success"). Leave the
   filter's "False" output unwired — that's the dead end for non-module attribute updates.

2. Add a **Script** *transformation* node (not the Script *filter* node — different category,
   same name) with this logic, so the outgoing payload always carries which module it came from,
   mapped to the real device names:

   ```javascript
   var deviceModuleMap = {
       'NodeRed #1': 'module1',
       'NodeRed #2': 'module2',
       'NodeRed #3': 'module3',
       'NodeRed #4': 'module4'
   };

   var mappedId = deviceModuleMap[metadata.deviceName];
   var moduleId = (mappedId != null) ? mappedId : metadata.deviceName;

   return {
       msg: {
           moduleId: moduleId,
           components_count: msg.components_count
       },
       metadata: metadata,
       msgType: msgType
   };
   ```

   **Important**: ThingsBoard's Script node doesn't run plain JavaScript — it runs **TBEL**
   (ThingsBoard Expression Language, built on Java's MVEL2), which looks JS-like but differs in
   places. In particular, `||` here isn't JS's truthy-fallback operator - it tries to cast both
   operands to actual `Boolean` and throws `ClassCastException: String cannot be cast to Boolean`
   if given a String (e.g. the common `foo || bar` "default value" idiom fails). Use an explicit
   `!= null` ternary instead, as above, not `||`, for anything that isn't already a boolean.

   Wire the filter node's "True" output → this Script node.

3. Add a **REST API Call** node, configured with:
   - **Endpoint URL**: `http://<node-red-host>:1880/digital-twin/ingest`
   - **Request method**: `POST`

   Wire the Script node's output → this REST API Call node.

4. Save/apply the rule chain.

That's the whole ThingsBoard-side change — everything else in your existing rule chain (device
provisioning, alarms, dashboards, whatever else you have) stays untouched.

## 3. Node-RED bridge flow

Build this as a **new flow tab**, on whichever Node-RED instance is convenient to reach from
ThingsBoard (doesn't need to be on one of the 4 Pis — a central server, or even the same host
ThingsBoard runs on, is simplest).

**Prerequisite**: install a Postgres client node for Node-RED once, in that instance's user
directory (**must be `~/.node-red`** — installing anywhere else means Node-RED never sees it):

```bash
cd ~/.node-red
npm install node-red-contrib-postgresql
```
This is the actively-maintained package that ended up working (installing via Node-RED's own
"Manage palette → Install" search UI is more reliable than the raw `npm install` CLI - a plain
CLI install can silently leave a broken `MODULE_NOT_FOUND` state; the in-editor installer handles
this correctly). Its node type is `postgresql`, and **parameter values go in `msg.params`**, not
`msg.payload` (`msg.payload` is reserved for the query *result*) — see its built-in help panel in
the editor (info/book icon) for the full docs.

**Flow shape**: `http in` → `function` (normalize) → two `postgresql` nodes (counts, status) →
`http response`

- **`http in`**: Method `POST`, URL `/digital-twin/ingest`. Wire its output to the function node
  below.

- **`function` node** ("Normalize payload"), 2 outputs — the code goes in the **"On Message" tab**
  specifically (not "On Start", which runs once at startup with no incoming `msg`; not "Setup",
  which is config only — set **Outputs = 2** there):

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

  // Row messages: no msg.res needed here - there can be zero, one, or many rows per
  // incoming request, and an HTTP response can only be sent once.
  const rowMsgs = rows.map(r => ({ params: r }));

  // Status message: exactly one per incoming request, so THIS is the one that carries the
  // rest of the original msg (msg.res / msg._msgid, needed by the http response node at the
  // end of the flow - a plain { params: [...] } object drops them, causing Node-RED's
  // http response node to error with "No response object").
  const statusMsg = { ...msg, params: [moduleId, 'online'] };

  return [rowMsgs, statusMsg];
  ```

  Wire output 1 (an array of messages — Node-RED's `function` node auto-splits an array-of-msgs
  output into separate sends) into the counts `postgresql` node, and output 2 into the status
  `postgresql` node.

- **`postgresql` node (counts)** — Server: `localhost:5432/digital_twin` (configured with the
  `digital_twin_bridge` role from step 1, not the `postgres` superuser) — query:
  ```sql
  INSERT INTO component_counts (module_id, part_type, color, count)
  VALUES ($1, $2, $3, $4)
  ```
  Doesn't need to be wired to anything after this — it's a dead end.

- **`postgresql` node (status)** — same Server config — query:
  ```sql
  INSERT INTO module_status (module_id, status, last_seen_at)
  VALUES ($1, $2, now())
  ON CONFLICT (module_id) DO UPDATE SET status = EXCLUDED.status, last_seen_at = now()
  ```

- **`http response`** node: wire from **only** the status `postgresql` node into it (not the
  counts node - since there can be zero/one/many count rows per request but only ever one status
  message, only the status branch is guaranteed to fire exactly once, which is what an HTTP
  response requires). This gives ThingsBoard's REST API Call node a clean `200 OK` once the
  status upsert completes, instead of timing out waiting for a reply.

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






sudo nano /etc/resolv.conf 

cd ~/.node-red
npm install node-red-contrib-postgres
sudo systemctl restart nodered

sudo systemctl restart nodered

sudo systemctl status nodered
curl -I http://localhost:1880

psql --version

sudo apt update && sudo apt install -y postgresql
  sudo systemctl enable --now postgresql

sudo -u postgres createdb digital_twin

cd 
cd /tmp
cp /home/pi/Desktop/digital_twin/schema.sql /tmp

sudo -u postgres psql -d digital_twin -f ~/Desktop/Modul/digital_twin/schema.sql

sudo -u postgres psql -d digital_twin -c "
INSERT INTO modules (module_id, name) VALUES
    ('module1', 'Module 1'),
    ('module2', 'Module 2'),
    ('module3', 'Module 3'),
    ('module4', 'Module 4');
"

sudo -u postgres psql -d digital_twin -c "SELECT * FROM modules;"

sudo -u postgres psql -d digital_twin -c "
CREATE ROLE digital_twin_bridge WITH LOGIN PASSWORD 'CHANGE_ME_TO_SOMETHING_REAL';
GRANT CONNECT ON DATABASE digital_twin TO digital_twin_bridge;
GRANT USAGE ON SCHEMA public TO digital_twin_bridge;
GRANT SELECT, INSERT, UPDATE ON component_counts, module_status, modules TO digital_twin_bridge;
GRANT USAGE, SELECT ON SEQUENCE component_counts_id_seq TO digital_twin_bridge;
"



Once that's run, let's build the actual flow in the Node-RED editor (http://<this-pi-ip>:1880):

New flow tab — click the + next to the existing tabs, name it something like "Digital Twin Bridge".

Drag in an http in node. Double-click it: Method = POST, URL = /digital-twin/ingest.

Drag in a function node, wire it from the http in node. Double-click it, set Outputs to 2 (under the Setup tab), and paste this into the function body:

const moduleId = msg.payload.moduleId;
const counts = msg.payload.components_count || {};

const rows = [];
for (const partType of Object.keys(counts)) {
    for (const color of Object.keys(counts[partType])) {
        rows.push([moduleId, partType, color, counts[partType][color]]);
    }
}

const statusMsg = { params: [moduleId, 'online'] };
const rowMsgs = rows.map(r => ({ params: r }));

return [rowMsgs, statusMsg];


Check the hamburger menu (top-right, three lines) -> 'Manage palette' -> 'Nodes' tab,
   search for 'postgres' there. This shows ALL installed nodes including ones hidden from
   the main palette view - if http-in is listed there but greyed out / toggled off,
   someone previously hid that category from the palette.

if it doenst work remove it and then install page and install: node-red-contrib-postgresql

Drag in two postgres nodes (search "postgres" in the palette). Wire the function node's output 1 into the first, output 2 into the second.

On the first postgres node's config (create new config node — click the pencil or + icon): 
Host localhost, 
Port 5432, 
Database digital_twin, 
User digital_twin_bridge, 
Password (what you just set), -> CHANGE_ME_TO_SOMETHING_REAL 
SSL false. 
This config node can be reused for the second postgres node too — no need to create it twice.

First postgres node's query: 
INSERT INTO component_counts (module_id, part_type, color, count) VALUES ($1, $2, $3, $4)

Second postgres node's query: 
INSERT INTO module_status (module_id, status, last_seen_at) VALUES ($1, $2, now()) ON CONFLICT (module_id) DO UPDATE SET status = EXCLUDED.status, last_seen_at = now()

Drag in an http response node, wire both postgres nodes into it.

Click Deploy (top right).

test:
curl -i -X POST http://localhost:1880/digital-twin/ingest \ \
  -H "Content-Type: application/json" \
  -d '{"moduleId": "module1", "components_count": {"trainEngine": {"red": 1}, "trainCabin": {"blue": 2}}}'


sudo -u postgres psql -d digital_twin -c "SELECT * FROM component_counts ORDER BY recorded_at DESC LIMIT 10;";"
sudo -u postgres psql -d digital_twin -c "SELECT * FROM module_status;"


clean the table:
sudo -u postgres psql -d digital_twin -c "TRUNCATE component_counts;"

check ce dela:
sudo -u postgres psql -d digital_twin -c "SELECT * FROM module_status;"
sudo -u postgres psql -d digital_twin -c "SELECT * FROM component_counts ORDER BY recorded_at DESC LIMIT 5;"
