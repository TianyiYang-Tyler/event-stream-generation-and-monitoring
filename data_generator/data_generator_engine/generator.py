import argparse
import importlib.util
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
    def __init__(self):
        self._events = {}

    def build_key(self, attributes, match_on_fields):
        values = []
        for field in match_on_fields:
            value = attributes.get(field)
            if value is None:
                raise KeyError(f"Missing match field: {field}")
            values.append(value)
        return tuple(values)

    def record(self, event_type, attributes, match_on_fields):
        key = self.build_key(attributes, match_on_fields)
        self._events[(event_type, tuple(match_on_fields), key)] = dict(attributes)

    def lookup(self, event_type, match_on_fields, match_key, attribute):
        data = self._events.get((event_type, tuple(match_on_fields), match_key))
        if data is None:
            raise KeyError(f"No prior event for {event_type} with key {match_key}")
        value = data.get(attribute)
        if value is None:
            raise KeyError(f"Attribute not found in {event_type}: {attribute}")
        return value


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

    if args.skeletons_in:
        tree = ET.parse(args.skeletons_in)
        root = tree.getroot()

        event_nodes = root.findall("Event")
        total_events = len(event_nodes)
        print(f"Filling {total_events} events from {args.skeletons_in}...", flush=True)

        for index, event in enumerate(event_nodes, start=1):
            if index % 100 == 0 or index == total_events:
                print(f"Processed {index}/{total_events} events", flush=True)
            event_type_elem = event.find("Type")
            if event_type_elem is None or event_type_elem.text is None:
                continue
            event_type = event_type_elem.text
            attributes_elem = event.find("Attributes")
            if attributes_elem is None:
                continue

            attributes = {}
            for attr_elem in attributes_elem.findall("Attribute"):
                name = attr_elem.get("name")
                if name is None:
                    continue
                attributes[name] = attr_elem.text

            context = {
                "event_type": event_type,
                "attributes": attributes,
                "runtime_state": runtime_state,
            }
            filler.fill_event_attributes(event_type, attributes, context)

            for match_fields in fill_spec.get_source_match_fields(event_type):
                runtime_state.record(event_type, attributes, match_fields)
            if "session_id" in attributes:
                runtime_state.record(event_type, attributes, ["session_id"])

            for attr_elem in attributes_elem.findall("Attribute"):
                name = attr_elem.get("name")
                if name is None:
                    continue
                if name in attributes:
                    attr_elem.text = str(attributes[name])

        Path(args.skeletons_out).parent.mkdir(parents=True, exist_ok=True)
        tree.write(args.skeletons_out, encoding="utf-8", xml_declaration=True)
        print(args.skeletons_out)
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
