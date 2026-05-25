# Data Generator

## Summary

This generator fills event skeleton XML files using a fill specification and
optional custom functions. It resolves dependencies between attributes, can
pull data from external sources (like a database), and emits a fully populated
skeletons_filled.xml in the example's output folder.

## Folder Structure

```
data_generator/
|-- data_generator_engine/
|   |-- .DS_Store
|   |-- Wallet_resources/
|   |-- __init__.py
|   |-- __pycache__/
|   |-- db_oracle.py
|   |-- generator.py
|   |-- validate_distributions.py
|   `-- validate_filled_skeleton.py
|-- bike_islavista_example/
|   |-- input/
|   |   |-- DATA_GENERATOR_SPECIFICATION.txt
|   |   |-- cepal.xml
|   |   |-- fill_spec.yaml
|   |   |-- functions.py
|   |   |-- resources.py
|   |   `-- skeletons.xml
|   `-- output/
|-- bike_sanfrancisco_example/
|   |-- input/
|   |   |-- DATA_GENERATOR_SPECIFICATION.txt
|   |   |-- cepal.xml
|   |   |-- fill_spec.yaml
|   |   |-- functions.py
|   |   |-- resources.py
|   |   `-- skeletons.xml
|   `-- output/
|-- bike_nyc_example/
|   |-- input/
|   |   |-- DATA_GENERATOR_SPECIFICATION.txt
|   |   |-- cepal.xml
|   |   |-- fill_spec.yaml
|   |   |-- functions.py
|   |   |-- resources.py
|   |   `-- skeletons.xml
|   `-- output/
```

- data_generator_engine/
  - Core generator code and runtime logic.
- bike_islavista_example/
  - Isla Vista scooter example (events: 1000; Users: 200; Stations: 15; Bikes: 65).
- bike_sanfrancisco_example/
  - San Francisco bike share example (events: 5000; Users: 3000; Stations: 300; Bikes: 2000).
- bike_nyc_example/
  - NYC bike share example (events: 10000; Users: 10000; Stations: 400; Bikes: 2000).

Each example folder is self-contained:

- input/ contains fill_spec.yaml, functions.py, and skeletons.xml, cepal.xml, and resources.py.
- output/ receives skeletons_filled.xml after generation.

### input/ Files

- fill_spec.yaml
  - Declares how each event attribute should be populated (generate, select,
    lookup, copy, or dependent_select) and any dependencies between fields.
- functions.py
  - Optional domain-specific Python functions referenced by fill_spec.yaml.
    These can pull from Oracle, generate values, or enforce business rules.
- skeletons.xml
  - Event skeletons with placeholder attributes to be filled by the generator.

## How The Generator Works

- Loads fill_spec.yaml and builds rules per event type and attribute.
- Loads functions.py and makes its functions available to the rules.
- Parses skeletons.xml, then fills each event's attributes in dependency order.
- Records runtime state (for example session_id or source matches) so later
  events can copy or look up values from earlier ones.
- Writes skeletons_filled.xml to the example's output/ folder.

## How To Run

Run the generator from the repository root (the parent of data_generator/):

    python3 data_generator/data_generator_engine/generator.py --fill-spec data_generator/example/input/fill_spec.yaml

What to replace:

- Replace example with another example folder name (e.g., dg_bike_example).
- Replace input/fill_spec.yaml if your example uses a different path.

Where to run it:

- Run the command from the repository root so the paths resolve correctly.

Output location:

- The generator writes to the output/ folder that matches the example you pass in.
  For the command above, it writes to data_generator/example/output/skeletons_filled.xml.

## Distribution Rules

fill_spec.yaml can include an optional distribution block per attribute. These
rules are validated by validate_distributions.py and help ensure generated data
matches expected proportions.

Common distribution types:

- random
  - Skip validation (useful for attributes that are intentionally random).
- categorical
  - Explicit value shares (for example, 80% existing users / 20% new users).
- uniform_over_column
  - Check that values are roughly uniform over a database column.
- top_fraction_share
  - Enforce that the top fraction of values accounts for a given share.

Example:

    events:
      RentBike:
        user_id:
          category: generate
          function_name: choose_or_generate_user
          params:
            probability_new: 0.2
          distribution:
            type: categorical
            values:
              existing: 0.8
              new: 0.2
            bucket_by:
              kind: db_membership
              seeded_max_user_id: 11000
            tolerance: 0.08
        station_id:
          category: select
          function_name: choose_station
          distribution:
            type: uniform_over_column
            table: Stations
            column: station_id
            tolerance: 0.10

Notes:

- bucket_by.db_membership uses seeded_max_user_id to separate "existing" from
  newly inserted IDs.
- tolerance is absolute (for example, 0.10 means +/- 10 percentage points).

## Validation

Validate filled skeletons against the fill_spec rules (copy dependencies, bounds):

    python3 data_generator/data_generator_engine/validate_filled_skeleton.py \
      --fill-spec data_generator/<example>/input/fill_spec.yaml \
      --filled data_generator/<example>/output/skeletons_filled.xml

Validate distributions defined in fill_spec.yaml:

    python3 data_generator/data_generator_engine/validate_distributions.py \
      --fill-spec data_generator/<example>/input/fill_spec.yaml \
      --filled data_generator/<example>/output/skeletons_filled.xml

## How resources.py Works

Each example's input/resources.py bootstraps the Oracle tables used by the
generator:

    python3 data_generator/<example>/input/resources.py

- Drops and recreates tables when DROP_EXISTING is enabled.
- Seeds Users, Stations, and Bikes with Faker-based data.
- Updates derived columns like bikes_available and capacity_available.
- Commits the transaction so generator runs can read the seeded rows.

These scripts are designed to be the primary initializer for the demo schema,
and the generator functions read from and update those tables during event
filling.

## Oracle Cloud Persistence

Some examples use Oracle as a persistent backing store for resources such as
Users, Stations, and Bikes. These records live in Oracle Cloud and are read
or updated by generator functions (for example, via get_connection in
data_generator_engine/db_oracle.py). When you run a resource loader script
like input/resources.py, it creates and populates tables in the target schema
and subsequent generator runs will read and update those rows.

Notes:

- Ensure Oracle connection settings and wallet files are configured before
  running any scripts that touch the database.
- The schema name is configurable in the resource loader script.
- If DROP_EXISTING is enabled, the script will drop and recreate tables.
