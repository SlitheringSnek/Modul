# Connecting Siemens Tecnomatix Plant Simulation to `digital_twin`

## Status as of 2026-09-01

The full pipeline below is **built and confirmed working with live production data**:

```
[Module 1..4] --MQTT--> [ThingsBoard] --Rule Chain--> [Node-RED bridge] --> [Postgres: digital_twin]
```

Every module already publishes `components_count` as a ThingsBoard Shared Attribute on every
detection run. A Rule Chain (filter → TBEL script → REST API Call) forwards it to a Node-RED
bridge flow, which writes it into a central `digital_twin` Postgres database. Confirmed end-to-end
with `NodeRed #1` / `module1` — real rows landing in `component_counts` and `module_status`
matching the live ThingsBoard dashboard.

**This document covers only what's left**: getting Plant Simulation to read that database. See
[`README.md`](README.md) and [`schema.sql`](schema.sql) in this same folder for the full backstory
and schema if you need it — you likely won't need to touch either of those again.

## What you're connecting to

- **Database**: `digital_twin`, PostgreSQL, running on the Pi/server that hosts the Node-RED
  bridge (find its IP by running `hostname -I` on that machine — call this `<bridge-host-ip>`
  below).
- **Port**: `5432` (Postgres default, not changed).
- **Tables** (see `schema.sql` for full definitions):
  - `modules (module_id, name, description)` — one row per physical module (`module1`..`module4`).
  - `component_counts (id, module_id, part_type, color, count, recorded_at)` — one row per
    (module, part_type, color) observation from a detection run. This is a time series: every run
    inserts new rows, it doesn't overwrite. Use `recorded_at` to get the latest state (query below).
  - `module_status (module_id, status, last_seen_at)` — one row per module, upserted each run, for
    "is this module currently online."
  - `module_positions (rig_id, module_name, center_x_cm, center_y_cm, angle, updated_at)` — one row
    per module currently visible to the camera rig, upserted each detection run (not a time series
    like `component_counts` — always the latest known position). Added 2026-09-02, confirmed working
    end-to-end into Postgres; not yet wired into Plant Simulation.

## Step 1: Open Postgres to the network (if Plant Simulation runs on a different machine)

Skip this if Plant Simulation somehow runs on the same machine as the database — it won't.
Run on the Postgres host (`<bridge-host-ip>`):

```bash
# Find the actual config file paths first:
sudo -u postgres psql -c "SHOW config_file;"
sudo -u postgres psql -c "SHOW hba_file;"

# Edit the config file SHOW config_file printed, find/set:
#   listen_addresses = '*'

# Edit the file SHOW hba_file printed, add this line:
#   host    digital_twin    all    192.168.9.0/24    scram-sha-256
# (adjust 192.168.9.0/24 to match your actual local subnet if different)

sudo systemctl restart postgresql

# If a firewall is active, allow the port:
sudo ufw status                  # check if ufw is even active first
sudo ufw allow 5432/tcp          # only if the above showed "active"
```

## Step 2: Create a read-only role for Plant Simulation

Don't reuse the bridge's write role. Run on the Postgres host:

```bash
sudo -u postgres psql -d digital_twin -c "
CREATE ROLE digital_twin_reader WITH LOGIN PASSWORD 'REPLACE_WITH_A_REAL_PASSWORD';
GRANT CONNECT ON DATABASE digital_twin TO digital_twin_reader;
GRANT USAGE ON SCHEMA public TO digital_twin_reader;
GRANT SELECT ON component_counts, module_status, modules, module_positions TO digital_twin_reader;
"
```

**Replace the password before running**, and share the real value with whoever configures the
ODBC connection through a separate channel (Slack/in person) — don't put it in a doc or commit.

If `digital_twin_reader` already exists from before `module_positions` existed, the `CREATE ROLE`
above will just error harmlessly ("role already exists") — run this instead to add the missing grant
without recreating anything:
```bash
sudo -u postgres psql -d digital_twin -c "GRANT SELECT ON module_positions TO digital_twin_reader;"
```

## Step 3: Install the PostgreSQL ODBC driver (on the Windows machine running Plant Simulation)

Download **psqlODBC** from postgresql.org (64-bit build, matching your Windows install) and run
the installer. No configuration needed at this step — just gets the driver registered with Windows.

## Step 4: Create an ODBC Data Source (DSN)

On the same Windows machine:

1. Start menu → search **"ODBC Data Sources (64-bit)"** → open it.
2. **Add** → select the **PostgreSQL Unicode(x64)** driver (installed in step 3).
3. Fill in:
   - **Data Source**: any name you like, e.g. `digital_twin` (this is what Plant Simulation will
     reference)
   - **Server**: `<bridge-host-ip>`
   - **Port**: `5432`
   - **Database**: `digital_twin`
   - **User Name**: `digital_twin_reader`
   - **Password**: the real password from Step 2
4. Click **Test** before saving — confirm it actually connects. If it fails here, it's a network/
   credentials problem to solve before touching Plant Simulation at all (check Steps 1–2 again).

## Step 5: Reading the data in Plant Simulation

Plant Simulation has a built-in **ODBC** interface object (class library, under the communication/
interface section) that you drag into your model frame, point at the DSN created above, and query
via SimTalk — results typically populate a **Table File** object your model logic then reads.

**I can't give exact menu paths or SimTalk method names with certainty here** — they've shifted
across Plant Simulation versions and I have no way to verify against whichever version you're
running. This is exactly the kind of thing to hand to Codex directly: point it at your actual
Plant Simulation installation, give it the query below, and have it work out the exact SimTalk
syntax against your real environment (the same way we iteratively debugged the ThingsBoard/Node-RED
side against the real running system, rather than guessing blind).

**A good starting query** — latest count per (module, part_type, color), i.e. current stock per
module:

```sql
SELECT DISTINCT ON (module_id, part_type, color)
    module_id, part_type, color, count, recorded_at
FROM component_counts
ORDER BY module_id, part_type, color, recorded_at DESC;
```

**Module online/offline status**:

```sql
SELECT module_id, status, last_seen_at FROM module_status;
```

**Current module positions from the camera rig** — already the latest per module (upserted, not a
time series), so no `DISTINCT ON`/ordering needed:

```sql
SELECT rig_id, module_name, center_x_cm, center_y_cm, angle, updated_at FROM module_positions;
```

## What to hand Codex

A concrete prompt to get it started with the actual specifics it needs, rather than starting from
nothing:

> I'm working in Siemens Tecnomatix Plant Simulation [your version here]. I need to connect to a
> PostgreSQL database via an existing ODBC DSN named `digital_twin`, run this query:
> `SELECT DISTINCT ON (module_id, part_type, color) module_id, part_type, color, count, recorded_at
> FROM component_counts ORDER BY module_id, part_type, color, recorded_at DESC;`, and populate a
> Table File object with the results so the rest of my simulation model can read current
> per-module component stock from it. Show me the exact class library object to use, the SimTalk
> method code, and how to trigger it (on a timer / manually / on model start).

Give it access to Plant Simulation's own Help (F1 on the ODBC class, if it can read that) for
version-exact API details — that's more reliable than anything pre-written here.
