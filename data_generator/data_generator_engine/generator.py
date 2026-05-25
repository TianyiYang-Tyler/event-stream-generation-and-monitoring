import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

import yaml


class FunctionRegistry:
    def __init__(self, module_path):
        self._module_path = Path(module_path)
        self._ensure_repo_root_on_path()
        self._module = self._load_module()

    def _ensure_repo_root_on_path(self):
        repo_root = Path(__file__).resolve().parents[1]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

    def _load_module(self):
        spec = importlib.util.spec_from_file_location("domain_functions", self._module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load functions module: {self._module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def get(self, function_name):
        fn = getattr(self._module, function_name, None)
        if fn is None:
            raise KeyError(f"Function not found: {function_name}")
        return fn


class FillSpec:
    def __init__(self, spec_path):
        self._spec_path = Path(spec_path)
        self._spec = self._load()

    def _load(self):
        with self._spec_path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def get_rule(self, event_type, attribute):
        events = self._spec.get("events", {})
        event_rules = events.get(event_type, {})
        rule = event_rules.get(attribute)
        if rule is None:
            raise KeyError(f"No fill rule for {event_type}.{attribute}")
        return rule

    def get_event_rules(self, event_type):
        events = self._spec.get("events", {})
        return events.get(event_type, {}) or {}

    def get_source_match_fields(self, event_type):
        events = self._spec.get("events", {})
        match_fields = []
        for _, rules in events.items():
            for rule in (rules or {}).values():
                if rule.get("category") != "copy":
                    continue
                if rule.get("source_event") != event_type:
                    continue
                match_on = rule.get("match_on")
                if match_on is None:
                    continue
                fields = [match_on] if isinstance(match_on, str) else list(match_on)
                fields_tuple = tuple(fields)
                if fields_tuple not in match_fields:
                    match_fields.append(fields_tuple)
        return match_fields


class RuntimeState:
    """Records filled events so later events can copy/look up earlier ones.

    Backed by an on-disk SQLite database in a temp file instead of a Python
    dict. This keeps process memory near-constant regardless of how many
    sessions/events the skeleton file contains (a 20 GB input can imply millions
    of sessions, which would be many GB if held in a dict). Nothing is ever
    evicted, so a lookup can never miss because of memory management -- the only
    misses are genuine "no such prior event", exactly as before.

    Semantics match the previous dict implementation:
      * a record is keyed by (event_type, match_on_fields, match_key);
      * recording the same key again overwrites (last-write-wins), so repeated
        ReportLocations for a session collapse to the most recent one, which is
        what choose_return_station expects.
    """

    def __init__(self, db_path=None):
        import sqlite3
        import tempfile

        if db_path is None:
            # Temp file (not :memory:) so RAM stays flat for huge inputs.
            fd, db_path = tempfile.mkstemp(prefix="runtime_state_", suffix=".sqlite")
            os.close(fd)
            self._owns_file = True
        else:
            self._owns_file = False
        self._db_path = db_path

        self._conn = sqlite3.connect(self._db_path)
        # Pragmas tuned for a write-heavy, single-process, transient store.
        self._conn.execute("PRAGMA journal_mode=OFF")
        self._conn.execute("PRAGMA synchronous=OFF")
        self._conn.execute("PRAGMA temp_store=MEMORY")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                full_key TEXT PRIMARY KEY,
                payload  TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

        # Buffer writes and flush to disk in large batches. Larger batches mean
        # far fewer commits; the buffer (a dict) is also fully readable for
        # lookups, so un-flushed records never force a premature flush.
        self._pending = {}  # full_key -> payload (dedupes within a batch)
        self._batch_size = 50000

        # Bounded LRU over recently recorded payloads. Sized comfortably larger
        # than any single session's working set so lookups for the current
        # session (the only ones that ever happen) are served from memory and
        # never touch disk. OrderedDict gives O(1) move-to-end / popitem.
        import collections

        self._cache = collections.OrderedDict()
        self._cache_limit = 100000

    @staticmethod
    def _encode_full_key(event_type, match_on_fields, match_key):
        import json

        return json.dumps(
            [event_type, list(match_on_fields), list(match_key)],
            separators=(",", ":"),
            default=str,
        )

    def build_key(self, attributes, match_on_fields):
        values = []
        for field in match_on_fields:
            value = attributes.get(field)
            if value is None:
                raise KeyError(f"Missing match field: {field}")
            values.append(value)
        return tuple(values)

    def record(self, event_type, attributes, match_on_fields):
        import json

        key = self.build_key(attributes, match_on_fields)
        full_key = self._encode_full_key(event_type, tuple(match_on_fields), key)
        payload = json.dumps(dict(attributes), default=str)

        # LRU cache (last-write-wins). Move/insert at the most-recent end.
        if full_key in self._cache:
            self._cache.move_to_end(full_key)
        self._cache[full_key] = payload
        if len(self._cache) > self._cache_limit:
            self._cache.popitem(last=False)  # evict least-recently-used

        # Buffer the write (dict dedupes repeated keys within a batch). Flush
        # only when the buffer is large -> very few commits.
        self._pending[full_key] = payload
        if len(self._pending) >= self._batch_size:
            self._flush_pending()

    def _flush_pending(self):
        if not self._pending:
            return
        self._conn.executemany(
            "INSERT OR REPLACE INTO events (full_key, payload) VALUES (?, ?)",
            self._pending.items(),
        )
        self._conn.commit()
        self._pending.clear()

    def lookup(self, event_type, match_on_fields, match_key, attribute):
        import json

        full_key = self._encode_full_key(event_type, tuple(match_on_fields), match_key)

        # 1) recent-LRU cache, 2) un-flushed write buffer, 3) on-disk table.
        # The first two cover the overwhelmingly common case (a lookup for the
        # current session, just recorded), so disk reads are rare and we never
        # force a flush just to satisfy a lookup.
        payload = self._cache.get(full_key)
        if payload is None:
            payload = self._pending.get(full_key)
        if payload is None:
            row = self._conn.execute(
                "SELECT payload FROM events WHERE full_key = ?", (full_key,)
            ).fetchone()
            if row is None:
                raise KeyError(f"No prior event for {event_type} with key {match_key}")
            payload = row[0]

        data = json.loads(payload)
        value = data.get(attribute)
        if value is None:
            raise KeyError(f"Attribute not found in {event_type}: {attribute}")
        return value

    def close(self):
        try:
            self._flush_pending()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass
        if getattr(self, "_owns_file", False):
            try:
                os.remove(self._db_path)
            except OSError:
                pass


class SkeletonFiller:
    def __init__(self, fill_spec, function_registry, runtime_state):
        self._fill_spec = fill_spec
        self._functions = function_registry
        self._runtime_state = runtime_state

    def _validate_identifier(self, value, field_name):
        if value is None:
            raise KeyError(f"lookup rule missing {field_name}")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError(f"Invalid SQL identifier for {field_name}: {value}")
        return value

    def _lookup_from_cache(self, cache, table, where_column, selected_columns, lookup_value):
        """Return rows ([tuple]) from the in-memory cache for supported
        table/key combos, or None to signal a DB fallback is required."""
        if cache is None:
            return None

        table_l = table.lower()
        where_l = where_column.lower()

        if table_l == "stations" and where_l == "station_id":
            source = cache.stations
        elif table_l == "users" and where_l == "user_id":
            source = cache.users
        else:
            return None

        try:
            key = int(lookup_value)
        except (TypeError, ValueError):
            key = lookup_value

        record = source.get(key)
        if record is None:
            # Key not in cache (e.g. unexpected id) -> fall back to DB.
            return None

        try:
            values = tuple(record[col.lower()] for col in selected_columns)
        except KeyError:
            # Requested a column the cache doesn't track -> fall back to DB.
            return None
        return [values]

    def _lookup_value(self, event_type, attribute, rule, context):
        from data_generator_engine.db_oracle import get_connection

        lookup_params = rule.get("params", {}) or {}

        table = self._validate_identifier(
            rule.get("table", lookup_params.get("table")), "table"
        )
        value_columns = rule.get("value_columns", lookup_params.get("value_columns"))
        if value_columns is None:
            value_column = self._validate_identifier(
                rule.get("value_column", lookup_params.get("value_column")),
                "value_column",
            )
            selected_columns = [value_column]
        else:
            if isinstance(value_columns, str):
                value_columns = [value_columns]
            selected_columns = [
                self._validate_identifier(column_name, "value_columns")
                for column_name in value_columns
            ]
            if not selected_columns:
                raise ValueError(
                    f"lookup rule for {event_type}.{attribute} must include at least one value column"
                )

        depends_on = rule.get("depends_on", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]

        lookup_on = rule.get("lookup_on", lookup_params.get("lookup_on"))
        if lookup_on is None:
            if len(depends_on) != 1:
                raise ValueError(
                    f"lookup rule for {event_type}.{attribute} must define lookup_on or exactly one depends_on"
                )
            lookup_on = depends_on[0]

        where_column = rule.get("where_column", lookup_params.get("where_column", lookup_on))
        lookup_on = self._validate_identifier(lookup_on, "lookup_on")
        where_column = self._validate_identifier(where_column, "where_column")

        lookup_value = context["attributes"].get(lookup_on)
        if lookup_value is None or str(lookup_value).startswith("NULL"):
            raise KeyError(
                f"lookup dependency {lookup_on} must be filled before {event_type}.{attribute}"
            )

        # Fast path: serve Stations/Users lookups from the in-memory cache
        # instead of opening a connection per lookup.
        cached_rows = self._lookup_from_cache(
            context.get("resource_cache"), table, where_column, selected_columns, lookup_value
        )
        if cached_rows is not None:
            rows = cached_rows
        else:
            conn = get_connection()
            cursor = conn.cursor()
            try:
                select_columns_sql = ", ".join(selected_columns)
                cursor.execute(
                    f"SELECT {select_columns_sql} FROM {table} WHERE {where_column} = :1",
                    (lookup_value,),
                )
                rows = cursor.fetchall()
            finally:
                cursor.close()
                conn.close()

        if not rows:
            raise ValueError(
                f"No lookup result for {event_type}.{attribute} with {where_column}={lookup_value}"
            )
        if len(rows) > 1:
            raise ValueError(
                f"Multiple lookup rows for {event_type}.{attribute} with {where_column}={lookup_value}"
            )
        if any(value is None for value in rows[0]):
            raise ValueError(
                f"Lookup returned NULL for {event_type}.{attribute} with {where_column}={lookup_value}"
            )
        if len(rows[0]) == 1:
            return rows[0][0]
        return tuple(rows[0])

    def fill_attribute(self, event_type, attribute, context):
        rule = self._fill_spec.get_rule(event_type, attribute)
        category = rule.get("category")
        current_value = context["attributes"].get(attribute)

        if category == "generate":
            fn = self._functions.get(rule["function_name"])
            params = rule.get("params", {})
            return fn(context, **params)

        if category == "select":
            fn = self._functions.get(rule["function_name"])
            params = rule.get("params", {})
            return fn(context, **params)

        if category == "dependent_select":
            fn = self._functions.get(rule["function_name"])
            params = rule.get("params", {})
            return fn(context, **params)

        if category == "lookup":
            return self._lookup_value(event_type, attribute, rule, context)

        if category == "copy":
            source_event = rule["source_event"]
            source_attribute = rule.get("source_attribute", attribute)
            match_on = rule.get("match_on")
            if match_on is None:
                raise KeyError(f"copy rule missing match_on for {event_type}.{attribute}")
            match_fields = [match_on] if isinstance(match_on, str) else list(match_on)
            for field in match_fields:
                value = context["attributes"].get(field)
                if value is None or str(value).startswith("NULL"):
                    return current_value
            try:
                match_key = self._runtime_state.build_key(context["attributes"], match_fields)
                return self._runtime_state.lookup(source_event, match_fields, match_key, source_attribute)
            except KeyError:
                return current_value

        raise NotImplementedError(f"Unsupported category: {category}")

    def plan_event_attributes(self, event_type):
        event_rules = self._fill_spec.get_event_rules(event_type)
        if not event_rules:
            return []

        planned_order = []
        temporary_marks = set()
        permanent_marks = set()

        def visit(attribute):
            if attribute in permanent_marks:
                return
            if attribute in temporary_marks:
                raise ValueError(f"Cycle detected in fill dependencies for {event_type}: {attribute}")

            temporary_marks.add(attribute)
            rule = event_rules.get(attribute, {})
            depends_on = rule.get("depends_on", [])
            if isinstance(depends_on, str):
                depends_on = [depends_on]

            for dependency in depends_on:
                if dependency not in event_rules:
                    continue
                visit(dependency)

            temporary_marks.remove(attribute)
            permanent_marks.add(attribute)
            planned_order.append(attribute)

        for attribute in event_rules:
            visit(attribute)

        return planned_order

    def fill_event_attributes(self, event_type, attributes, context):
        event_rules = self._fill_spec.get_event_rules(event_type)
        planned_attributes = self.plan_event_attributes(event_type)

        for attribute in planned_attributes:
            rule = event_rules[attribute]
            current_value = attributes.get(attribute)
            if current_value is not None and not str(current_value).startswith("NULL"):
                continue
            attributes[attribute] = self.fill_attribute(event_type, attribute, context)


def parse_args():
    parser = argparse.ArgumentParser(description="Fill a single attribute using fill_spec.yaml")
    parser.add_argument(
        "--fill-spec",
        default=None,
        help="Path to fill_spec.yaml",
    )
    parser.add_argument(
        "--functions",
        default=None,
        help="Path to domain-specific functions module",
    )
    parser.add_argument("--event-type", default="RentBike", help="Event type name")
    parser.add_argument("--attribute", default="user_id", help="Attribute name")
    parser.add_argument(
        "--skeletons-in",
        default=None,
        help="Path to input skeletons.xml (if provided, fills matching attributes)",
    )
    parser.add_argument(
        "--skeletons-out",
        default=None,
        help="Path to write filled skeletons.xml",
    )
    return parser.parse_args()


def _resolve_default_path(provided, preferred, fallback):
    if provided:
        return provided
    preferred_path = Path(preferred)
    if preferred_path.exists():
        return str(preferred_path)
    return fallback


def _resolve_default_output_path(provided, preferred, fallback):
    if provided:
        return provided
    return str(preferred) if preferred else fallback


def _event_time_key(event):
    """Return a sort key (sortable_flag, numeric_time) for an Event element.

    Events whose <Time> is missing or non-numeric sort after all numeric
    ones, preserving their original relative order via a stable sort.
    """
    time_elem = event.find("Time")
    if time_elem is None or time_elem.text is None:
        return (1, 0.0)
    text = time_elem.text.strip()
    try:
        return (0, float(text))
    except (TypeError, ValueError):
        return (1, 0.0)


def _direct_event_time_key(event):
    """Return a sort key (sortable_flag, numeric_time) for direct event nodes."""
    time_text = event.get("time")
    if time_text is None:
        return (1, 0.0)
    try:
        return (0, float(time_text))
    except (TypeError, ValueError):
        return (1, 0.0)


def _sort_events_by_time(root):
    """Reorder <Event> children of root by <Time>, increasing (stable).

    Non-Event children keep their positions; only the Event nodes are
    reordered, slotted back into the positions Events originally occupied.
    """
    children = list(root)
    event_positions = [i for i, child in enumerate(children) if child.tag == "Event"]
    if len(event_positions) <= 1:
        return

    events = [children[i] for i in event_positions]
    events.sort(key=_event_time_key)  # stable: ties keep original order

    for slot, event in zip(event_positions, events):
        children[slot] = event

    root[:] = children


def _sort_direct_events_by_time(root):
    """Reorder direct event children of root by time attribute (stable)."""
    children = list(root)
    if len(children) <= 1:
        return

    events = list(children)
    events.sort(key=_direct_event_time_key)
    root[:] = events


def _extract_structured_event(event):
    """Parse an <Event><Type>..</Type><Attributes>..</Attributes></Event> node.

    Returns (event_type, attributes_dict, attr_elems) or None if the node is
    not a well-formed structured event. attr_elems is the list of <Attribute>
    elements so their text can be written back after filling.
    """
    event_type_elem = event.find("Type")
    if event_type_elem is None or event_type_elem.text is None:
        return None
    attributes_elem = event.find("Attributes")
    if attributes_elem is None:
        return None
    attr_elems = attributes_elem.findall("Attribute")
    attributes = {}
    for attr_elem in attr_elems:
        name = attr_elem.get("name")
        if name is None:
            continue
        attributes[name] = attr_elem.text
    return event_type_elem.text, attributes, attr_elems


def _write_back_structured(attributes, attr_elems):
    for attr_elem in attr_elems:
        name = attr_elem.get("name")
        if name is not None and name in attributes:
            attr_elem.text = str(attributes[name])


def _extract_flat_event(event):
    """Parse a flat event node like <RentBike><user_id>..</user_id>..</RentBike>.

    The node's tag is the event type; its child tags are attribute names.
    Returns (event_type, attributes_dict).
    """
    attributes = {
        child.tag: child.text for child in event if isinstance(child.tag, str)
    }
    return event.tag, attributes


def _write_back_flat(event, attributes):
    for child in event:
        name = child.tag
        if name in attributes:
            child.text = str(attributes[name])


def _stream_fill_skeletons(
    args,
    fill_spec,
    filler,
    runtime_state,
    resource_cache,
    match_fields_cache,
    close_pool,
):
    """Fill a skeletons.xml of arbitrary size in a single streaming pass.

    Memory stays bounded regardless of input size:
      * Input is parsed incrementally with ET.iterparse; each top-level event
        element is processed then dropped from the tree (elem.clear() plus
        removal from the root), so the parsed DOM never accumulates.
      * Output is written event-by-event to disk; no output tree is built.
      * runtime_state is backed by on-disk SQLite, so it stays bounded in RAM
        regardless of how many sessions/events the file contains. Nothing is
        evicted, so a lookup never misses due to memory management.

    Output preserves input document order (no global time sort).

    Both skeleton layouts are supported and auto-detected per element:
      * structured: <Event><Type>..</Type><Attributes>..</Attributes></Event>
      * flat:       <RentBike><user_id>..</user_id>..</RentBike>
    """
    out_path = Path(args.skeletons_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0

    def process(event_type, attributes):
        """Run the fill + record logic shared by both layouts."""
        context = {
            "event_type": event_type,
            "attributes": attributes,
            "runtime_state": runtime_state,
            "resource_cache": resource_cache,
        }
        filler.fill_event_attributes(event_type, attributes, context)

        if event_type not in match_fields_cache:
            match_fields_cache[event_type] = fill_spec.get_source_match_fields(event_type)
        for match_fields in match_fields_cache[event_type]:
            runtime_state.record(event_type, attributes, match_fields)
        if "session_id" in attributes:
            runtime_state.record(event_type, attributes, ["session_id"])

    # iterparse yields (event, elem) on element start/completion. We track tree
    # depth so we can identify top-level event elements (depth 1) unambiguously:
    # the root is depth 0, each event is depth 1, attribute elements are deeper.
    # Inner elements complete ("end") before their parent event, so we only act
    # on depth-1 "end" events.
    context_iter = ET.iterparse(args.skeletons_in, events=("start", "end"))
    root = None
    depth = 0

    print(f"Streaming fill from {args.skeletons_in}...", flush=True)

    try:
        with out_path.open("w", encoding="utf-8") as out:
            out.write('<?xml version="1.0" encoding="utf-8"?>\n')
            root_tag_written = False

            for ev, elem in context_iter:
                if ev == "start":
                    if root is None:
                        # Outermost element is the stream root (depth 0).
                        root = elem
                    depth += 1
                    continue

                # ev == "end"
                depth -= 1

                # depth 0 here means the root element just closed -> done.
                if depth == 0:
                    continue

                # Only depth-1 elements are top-level events. Deeper "end" events
                # are inner attribute elements; skip them (their parent reads
                # their text when it is processed below).
                if depth != 1:
                    continue

                # Write the opening root tag lazily, once, using the real root
                # tag and any attributes it carried.
                if not root_tag_written and root is not None:
                    attrs = "".join(
                        f' {k}="{_xml_attr_escape(v)}"' for k, v in root.attrib.items()
                    )
                    out.write(f"<{root.tag}{attrs}>\n")
                    root_tag_written = True

                # Decide layout: a structured event is an <Event> with a <Type>
                # child; everything else at depth 1 is treated as a flat event
                # whose tag is the event type.
                structured = None
                if elem.tag == "Event":
                    structured = _extract_structured_event(elem)

                if structured is not None:
                    event_type, attributes, attr_elems = structured
                    process(event_type, attributes)
                    _write_back_structured(attributes, attr_elems)
                else:
                    event_type, attributes = _extract_flat_event(elem)
                    process(event_type, attributes)
                    _write_back_flat(elem, attributes)

                # .strip() removes the element's preserved tail whitespace
                # (the newline that followed it in the input file); we then add
                # exactly one newline so output is one event per line with no
                # blank lines between events.
                out.write(ET.tostring(elem, encoding="unicode").strip())
                out.write("\n")

                total += 1
                if total % 1000 == 0:
                    print(f"Processed {total} events", flush=True)

                # Free this event and any already-processed siblings. Detaching
                # from root lets the parser reclaim memory; clear() drops the
                # element's own children/text.
                elem.clear()
                if root is not None:
                    # Remove all children processed so far. Removing just the
                    # current elem is O(n) per call on a list; clearing the whole
                    # child list periodically is cheaper and safe because we have
                    # already serialized them.
                    del root[:]

            if not root_tag_written:
                # Empty / unrecognized input: emit a minimal well-formed root so
                # the output is still valid XML.
                out.write((root.tag if root is not None else "EventStream").join(("<", ">\n")))
                root_tag_written = True
                if root is not None:
                    out.write(f"</{root.tag}>\n")
            else:
                out.write(f"</{root.tag}>\n")

        # Persist all in-memory station/bike state and new users in one batched
        # flush, then commit once.
        resource_cache.flush()
    finally:
        resource_cache.close()
        runtime_state.close()
        close_pool()

    print(f"Processed {total} events total", flush=True)
    print(str(out_path))


def _xml_attr_escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def main():
    args = parse_args()
    cwd = Path.cwd()
    args.fill_spec = _resolve_default_path(
        args.fill_spec,
        cwd / "input" / "fill_spec.yaml",
        "dg_bike_example/input/fill_spec.yaml",
    )

    base_dir = cwd
    fill_spec_path = Path(args.fill_spec)
    if fill_spec_path.exists():
        if fill_spec_path.parent.name == "input":
            base_dir = fill_spec_path.parent.parent
        else:
            base_dir = fill_spec_path.parent

    args.functions = _resolve_default_path(
        args.functions,
        base_dir / "input" / "functions.py",
        "dg_bike_example/input/functions.py",
    )
    args.skeletons_in = _resolve_default_path(
        args.skeletons_in,
        base_dir / "input" / "skeletons.xml",
        args.skeletons_in,
    )
    args.skeletons_out = _resolve_default_output_path(
        args.skeletons_out,
        base_dir / "output" / "skeletons_filled.xml",
        "dg_bike_example/output/skeletons_filled.xml",
    )

    fill_spec = FillSpec(args.fill_spec)
    functions = FunctionRegistry(args.functions)
    runtime_state = RuntimeState()
    filler = SkeletonFiller(fill_spec, functions, runtime_state)

    from data_generator_engine.db_oracle import ResourceCache, close_pool, get_connection

    # Build the in-memory resource cache once: one connection, read Stations,
    # Users and Bikes a single time. All availability/capacity/status changes
    # happen in memory and are flushed back in one batch at the end.
    resource_cache = ResourceCache(get_connection()).load()

    # get_source_match_fields scans the whole spec; cache it per event type.
    match_fields_cache = {}

    if args.skeletons_in:
        _stream_fill_skeletons(
            args=args,
            fill_spec=fill_spec,
            filler=filler,
            runtime_state=runtime_state,
            resource_cache=resource_cache,
            match_fields_cache=match_fields_cache,
            close_pool=close_pool,
        )
        return

    context = {
        "event_type": args.event_type,
        "attribute": args.attribute,
        "attributes": {},
        "runtime_state": runtime_state,
    }
    value = filler.fill_attribute(args.event_type, args.attribute, context)
    print(value)


if __name__ == "__main__":
    main()
