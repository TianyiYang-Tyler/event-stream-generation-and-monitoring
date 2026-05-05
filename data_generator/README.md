# Data Generator

## Summary

This generator fills event skeleton XML files using a fill specification and
optional custom functions. It resolves dependencies between attributes, can
pull data from external sources (like a database), and emits a fully populated
skeletons_filled.xml in the example's output folder.

## Folder Structure

- data_generator_engine/
  - Core generator code and runtime logic.
- dg_bike_example/
  - Example dataset with input/ and output/ folders.
- dg_bike_example_50/
  - Another example dataset with input/ and output/ folders.
- bike_islavista_example/
  - Isla Vista scooter example with input/ and output/ folders.

Each example folder is self-contained:

- input/ contains fill_spec.yaml, functions.py, and skeletons.xml.
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

## How resources.sql Works

The example resources.sql (under an example's input/ folder) bootstraps the
Oracle tables used by the generator:

- Creates the example-specific tables with primary keys and any needed foreign
  keys or constraints.
- Inserts sample rows in a deterministic order using INSERT ALL blocks.
- Runs any post-load updates needed to keep derived columns in sync.
- Commits the transaction.

The file is designed to be a one-time initializer for a demo schema, and the
generator functions read from and update these tables during event filling.
