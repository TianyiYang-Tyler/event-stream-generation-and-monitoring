# Pseudoreal Event Data Generator

A data generator engine that converts CEPAL event skeleton files (with NULL attribute placeholders) into fully populated, pseudoreal event streams. Built for the UCSB Early Research Scholars Program.

---

## What This Project Does

CEPAL (Complex Event Processing for Application Language) produces typed, ordered, and correlated event skeletons — but leaves all attribute values as NULL placeholders. This engine fills those placeholders with pseudoreal values that are:

- **Consistent across events** within a session (e.g. the same `user_id` copied through every event in an order)
- **Role- and constraint-aware** (e.g. an approver must be from the correct department)
- **Distribution-faithful** (e.g. a 60/40 existing-vs-new user split, or a weighted star-rating distribution)
- **Resource-backed** (values are looked up from or written to Oracle DB tables seeded by `resources.py`)

The engine is domain-independent — only the configuration files (`fill_spec.yaml`, `functions.py`, `resources.py`) change per example. The engine itself (`generator.py`, `db_oracle.py`) is shared.

---

## Repository Structure

```
event-stream-generation-and-monitoring/
│
├── data_generator/
│   │
│   ├── data_generator_engine/          # Shared engine — do not modify per example
│   │   ├── generator.py                # Main fill engine (stream-fills skeletons.xml → filled_skeletons.xml)
│   │   ├── db_oracle.py                # Schema-generic Oracle cache (ResourceCache)
│   │   ├── sort_by_time.py             # Post-processing: sorts filled output by event time
│   │   └── Wallet_resources/           #  ⚠️ PLACE HERE
│   │
│   ├── bike_sanfrancisco_example/
│   │   ├── input/
│   │   │   ├── cepal.xml               # CEPAL schema: event definitions, types, constraints
│   │   │   ├── fill_spec.yaml          # Fill rules per event/attribute (categories, distributions, params)
│   │   │   ├── functions.py            # Domain logic: user selection, station/bike selection, location generation
│   │   │   ├── resources.py            # One-time Oracle seed: creates and populates Stations, Users, Bikes tables
│   │   │   └── skeletons.xml           # ⚠️ PLACEHOLDER ONLY — real empty skeletons are in Google Drive
│   │   └── output/
│   │       ├── validation_report.txt   # Description of the results of filling the skeleton stream
│   │       └── [filled_skeletons.xml]  # ⚠️ Lives in Google Drive — see "Data Files" section below
│   │
│   ├── bike_nyc_example/               # Same structure as SF example
│   ├── bike_islavista_example/         # Same structure as SF example
│   │
│   ├── shopping_universitystore_example/   # Same structure
│   ├── shopping_grocerydelivery_example/   # Same structure
│   ├── shopping_amazinmart_example/        # Same structure
│   │
│   ├── roomkey_university_example/     # Same structure
│   ├── roomkey_hotel_example/          # Same structure
│   ├── roomkey_techcompany_example/    # Same structure
│   │
│   └── [example]/
│       ├── input/
│       │   ├── cepal.xml
│       │   ├── fill_spec.yaml
│       │   ├── functions.py
│       │   ├── resources.py
│       │   └── skeletons.xml           # ⚠️ PLACEHOLDER — real file in Google Drive
│       └── output/
│           ├── validation_report.txt   # Description of the results of filling the skeleton stream
│           └── [filled_skeletons.xml]  # ⚠️ PLACEHOLDER — real file in Google Drive
```

---

## Data Files (Google Drive)

> **Important for new contributors:** The skeleton and filled output XML files are too large for Git and live in Google Drive. The `skeletons.xml` files committed to this repo are empty placeholders only.


Ask a current team member for the Google Drive link. Before running the generator on an example, download the appropriate `skeletons.xml` from Google Drive and place it at `data_generator/<example>/input/skeletons.xml`.

The filled output (`filled_skeletons.xml`) should be saved to the `output/` folder of the relevant example — both locally and in the corresponding Google Drive folder.

---

## Examples

Nine examples are currently implemented across three domains. All use the same engine; only the per-example config files differ.

| Example | Domain | Events | Session Key | Seeded Tables |
|---|---|---|---|---|
| `bike_sanfrancisco_example` | Bike rental | 750K | `session_id` | Stations, Users, Bikes |
| `bike_nyc_example` | Bike rental | 1M | `session_id` | Stations, Users, Bikes |
| `bike_islavista_example` | Bike rental | 100K | `session_id` | Stations, Users, Bikes |
| `shopping_universitystore_example` | Online shopping | 100K | `order_id` | Users, Products |
| `shopping_grocerydelivery_example` | Online shopping | 750K | `order_id` | Users, Products |
| `shopping_amazinmart_example` | Online shopping | 980K | `order_id` | Users, Products, Warehouses |
| `roomkey_university_example` | Room access approval | 100K | `application_id` | Employees, Departments |
| `roomkey_hotel_example` | Room access approval | 750K | `application_id` | Employees, Departments |
| `roomkey_techcompany_example` | Room access approval | 1M | `application_id` | Employees, Departments |

### Domain Lifecycles

**Bike rental** — `RentBike → ReportLocation* → ReturnBike`
A user (80% existing / 20% new) rents a bike from a station with available bikes. ReportLocation events trace the ride within a configured max-mile radius. ReturnBike selects a return station within range of the last reported location and updates station/bike availability in memory (flushed to Oracle at the end).

**Online shopping** — `Order → AddItem → Confirm_payment → Ship → Confirm_arrival → Delivery_out → Confirm_delivery → Rate_order`
A user (60% existing / 40% new) places an order. `user_id`, `shipping_location`, and `order_details` are consistent across all 8 events via copy rules. `AddItem` decrements product stock. `Rate_order` produces a weighted 5/4/3/2/1 star rating with a decision-consistent comment.

**Room access approval** — `Apply → Department_approval → CRS_approval → Notify`
An applicant submits a request. `Department_approval` must be filled by an approver in the **same department** as the applicant, and must be a distinct person from the applicant and the CRS approver. `Notify.decision` is `AP` if and only if both prior approvals are `AP`.

---

## How to Run an Example (End to End)

### Prerequisites

- Python 3.10+ with `.venv` activated
- Oracle Cloud wallet in `data_generator/data_generator_engine/Wallet_resources/`
- Dependencies: `oracledb`, `faker`, `pyyaml` (install via `pip install -r requirements.txt`)

### Step 1 — Seed Oracle tables (run once per example, or after schema changes)

```bash
python3 data_generator/<example>/input/resources.py
```

This creates and populates the Oracle tables the generator reads from (e.g. `Users`, `Products`, `Employees`). Safe to re-run — it drops and recreates tables by default.

### Step 2 — Place the skeleton file

Download the appropriate `skeletons.xml` from Google Drive and place it at:
```
data_generator/<example>/input/skeletons.xml
```

### Step 2 — Run the generator on the full skeleton

```bash
python3 data_generator/data_generator_engine/generator.py \
  --fill-spec data_generator/<example>/input/fill_spec.yaml
```

`--fill-spec` auto-resolves `functions.py` and `skeletons.xml` from the same `input/` folder and writes output to `output/skeletons_filled.xml`. To specify paths explicitly:

```bash
python3 data_generator/data_generator_engine/generator.py \
  --fill-spec data_generator/<example>/input/fill_spec.yaml \
  --skeletons-in data_generator/<example>/input/skeletons.xml \
  --skeletons-out data_generator/<example>/output/skeletons_filled.xml
```

### Step 3 — Sort the filled output by time

> ⚠️ **Current limitation:** sorting is a manual post-processing step. See Future Work.

The filled output preserves the input's session-grouped order, not global time order. Sort it before validation or analysis:

```bash
python3 data_generator/data_generator_engine/sort_by_time.py \
  data_generator/<example>/output/skeletons_filled.xml \
  --out data_generator/<example>/output/skeletons_filled_sorted.xml
```

`sort_by_time.py` uses external merge-sort, so it is safe to run on large files (tested up to 1M events).

---

## Key Configuration Files

### `fill_spec.yaml`

Declares how each attribute of each event type is filled. The engine reads this file and dispatches to the appropriate fill strategy. Top-level keys:

```yaml
resources:
  tables:
    Users:               # Table name
      primary_key: user_id
      pk_column: id
      columns: [id, user_id, first_name, ...]
      insertable: true   # Whether new rows can be added at runtime
      id_sequence: true  # Whether next_ids() is supported
      mutable_columns: [status]  # Columns written back on flush
      where: user_id IS NOT NULL  # Optional load filter

events:
  Order:                 # Event type name (must match skeleton XML)
    user_id:             # Attribute name (must match skeleton XML child element)
      category: generate
      function_name: choose_or_generate_user
      params:
        probability_new: 0.4
      distribution:      # Optional: declares expected distribution for validation
        type: categorical
        values: {existing: 0.6, new: 0.4}
        tolerance: 0.08
```

**Fill categories:**

| Category | What it does |
|---|---|
| `generate` | Calls a function to produce a value; function receives `(context, **params)` |
| `dependent_generate` | Like `generate` but waits for `depends_on` attributes to be filled first |
| `select` | Calls a function that selects from a resource table (e.g. choose a station) |
| `dependent_select` | Like `select` but waits for `depends_on` attributes first |
| `lookup` | SQL SELECT from a resource table; can be served from cache |
| `copy` | Copies a value from a previously filled event matched by `match_on` key |

### `functions.py`

Contains Python functions called by the engine. All functions must have the signature:

```python
def my_function(context, param1=default1, param2=default2):
    cache = context.get("resource_cache")   # ResourceCache instance
    attrs = context.get("attributes", {})   # Already-filled attributes of current event
    runtime_state = context.get("runtime_state")  # For cross-event lookups
    event_type = context.get("event_type")  # Current event type string
    ...
    return value  # The value to fill into the attribute
```

Functions interact with the cache via:
- `cache.table("Users")` → `{pk_value: rowdict}` — read a full table
- `cache.next_ids("Users")` → `(primary_key, pk_column)` — reserve a new ID
- `cache.add_row("Users", rowdict)` — register a new row (queued for insert)
- `cache.mark_dirty("Users", pk)` — flag a row for UPDATE at flush

For cross-event lookups (e.g. looking up a prior event's decision):
```python
match_key = runtime_state.build_key(attrs, ["application_id"])
value = runtime_state.lookup("Department_approval", ["application_id"], match_key, "decision")
```

### `resources.py`

A one-time seed script. Run it once before the generator to create and populate Oracle tables. It is standalone — not called by the engine at fill time. Every example has its own `resources.py` with domain-specific table schemas and seed data.

### `db_oracle.py` (engine — shared)

The `ResourceCache` class loads Oracle tables into memory at startup (one `SELECT` per table declared in `fill_spec.yaml`'s `resources:` block), serves all cache reads in memory during filling, and flushes inserts/updates back to Oracle in one batch at the end. The schema is driven entirely by `fill_spec.yaml` — `db_oracle.py` itself has no hardcoded table names.

---

## Adding a New Example

1. Create `data_generator/<your_example>/input/` and `output/` folders.
2. Write `resources.py` — define and seed the Oracle tables your example needs.
3. Write `fill_spec.yaml` — declare the `resources:` block (matching your tables) and `events:` block (one entry per event type, one rule per attribute).
4. Write `functions.py` — implement any `generate`/`select`/`dependent_*` functions referenced in the spec. All functions take `(context, **params)`.
5. Obtain or generate a `skeletons.xml` from CEPAL and place it in `input/`.
6. Run `resources.py` to seed Oracle, then `generator.py` to fill.
7. Run `sort_by_time.py` on the output.
8. Write a `validate_<example>.py` to check the output's distributions and constraints.

The existing examples (especially `roomkey_university_example`) are the cleanest templates to copy from.

---

## Validation Reports

Each example has an associated validation report (`.txt`) describing the filled skeletons for that example. These reports currently live alongside the example's `output/` folder and describe the filled skeletons stored in Google Drive.

> ⚠️ **Current limitation:** validation reports are generated manually, per example, from locally-run scripts. They are not automatically produced as part of the generation pipeline. See Future Work.

---

## Current Limitations and Future Work

### Sorting is a manual post-processing step
`sort_by_time.py` must be run manually after `generator.py`. The intended future state is for sorting to be incorporated automatically into the generation pipeline — either as a final stage of `generator.py` itself, or as an automatic step before the output is written.

### Validation is example-specific and not automated
Each example has its own hand-written `validate_*.py` script with hardcoded thresholds (e.g. `--seeded-max-employee-id`). Future work is to build a single generic validation script that reads all constraints and distribution targets from `fill_spec.yaml` and validates any filled skeleton automatically, without per-example code.

### No input file validation
There is currently no tooling to validate the input files before a run. A future validator should check:
- That every `function_name` in `fill_spec.yaml` exists in `functions.py`
- That every `table` referenced in `fill_spec.yaml` exists in the `resources:` block
- That every `source_event` in `copy` rules exists as an event type in the spec
- That the `cepal.xml` schema is internally consistent and matches the skeleton structure
- That column names in `resources:` match the actual Oracle table definitions

### Skeleton and output files are not in the repo
Large XML files live in Google Drive. Future work includes either a lightweight file registry (listing what lives where), an automated download script, or a pipeline that generates skeletons on demand rather than requiring manual placement.

### Validation reports are not tied to the pipeline
Reports are currently produced manually. Future work is to make validation an automatic step that runs after generation and produces a report in `output/` alongside the filled skeleton, so there is always a report paired with each filled file.
