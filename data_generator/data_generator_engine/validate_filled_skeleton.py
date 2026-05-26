from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET

from generator import FillSpec, RuntimeState


def parse_location(value):
	if value is None:
		return None
	text = str(value).strip()
	if text.startswith("(") and text.endswith(")"):
		text = text[1:-1]
	parts = [part.strip() for part in text.split(",")]
	if len(parts) >= 2:
		try:
			return float(parts[0]), float(parts[1])
		except ValueError:
			return None
	return None


def parse_bounds(bounds_arg):
	if not bounds_arg:
		return None
	if len(bounds_arg) != 4:
		raise ValueError("bounds requires 4 values: lon_min lon_max lat_min lat_max")
	return tuple(float(value) for value in bounds_arg)


def load_bounds_from_example(fill_spec_path):
	fill_spec_dir = Path(fill_spec_path).resolve().parent
	resources_path = fill_spec_dir / "resources.py"
	if not resources_path.exists():
		return None

	spec = importlib.util.spec_from_file_location("example_resources", resources_path)
	if spec is None or spec.loader is None:
		return None
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)

	for name in dir(module):
		if not name.endswith("_BOUNDS"):
			continue
		value = getattr(module, name)
		if isinstance(value, (list, tuple)) and len(value) == 4:
			return tuple(float(part) for part in value)

	return None


def is_null(value):
	return value is None or str(value).startswith("NULL")


def validate_copy_rule(event_type, attr_name, rule, attributes, runtime_state, errors):
	source_event = rule.get("source_event")
	source_attr = rule.get("source_attribute")
	match_on = rule.get("match_on")
	if source_event is None or source_attr is None or match_on is None:
		errors.append(f"{event_type}.{attr_name}: copy rule is incomplete")
		return

	match_on_fields = [match_on] if isinstance(match_on, str) else list(match_on)
	try:
		match_key = runtime_state.build_key(attributes, match_on_fields)
		expected = runtime_state.lookup(source_event, match_on_fields, match_key, source_attr)
	except KeyError as exc:
		errors.append(f"{event_type}.{attr_name}: copy lookup failed ({exc})")
		return

	value = attributes.get(attr_name)
	if str(value) != str(expected):
		errors.append(
			f"{event_type}.{attr_name}: copy mismatch (expected {expected}, got {value})"
		)


def validate_location_bounds(event_type, attr_name, value, bounds, errors):
	coords = parse_location(value)
	if coords is None:
		errors.append(f"{event_type}.{attr_name}: invalid location format")
		return
	lon, lat = coords
	lon_min, lon_max, lat_min, lat_max = bounds
	if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
		errors.append(f"{event_type}.{attr_name}: out of bounds")


def validate_event(event_type, attributes, fill_spec, runtime_state, bounds, errors, warnings):
	rules = fill_spec.get_event_rules(event_type)
	if not rules:
		warnings.append(f"{event_type}: no fill_spec rules; skipping validation")
		return
	for attr_name, rule in rules.items():
		value = attributes.get(attr_name)
		if is_null(value):
			errors.append(f"{event_type}.{attr_name}: missing value")
			continue

		category = rule.get("category")
		if category == "copy":
			validate_copy_rule(event_type, attr_name, rule, attributes, runtime_state, errors)

		if attr_name == "location_data" and bounds:
			validate_location_bounds(event_type, attr_name, value, bounds, errors)


def main():
	parser = argparse.ArgumentParser(description="Validate filled skeletons against fill_spec rules.")
	parser.add_argument("--filled", required=True, help="Path to filled skeletons.xml")
	parser.add_argument("--fill-spec", required=True, help="Path to fill_spec.yaml")
	parser.add_argument(
		"--bounds",
		nargs=4,
		metavar=("LON_MIN", "LON_MAX", "LAT_MIN", "LAT_MAX"),
		help="Optional bounds to validate location_data",
	)
	args = parser.parse_args()

	bounds = parse_bounds(args.bounds)
	if bounds is None:
		bounds = load_bounds_from_example(args.fill_spec)
	fill_spec = FillSpec(args.fill_spec)
	runtime_state = RuntimeState()

	tree = ET.parse(args.filled)
	root = tree.getroot()

	errors = []
	warnings = []
	event_count = 0

	legacy_events = root.findall("Event")
	if legacy_events:
		for event in legacy_events:
			event_type_elem = event.find("Type")
			if event_type_elem is None or event_type_elem.text is None:
				warnings.append("Event missing Type")
				continue
			event_type = event_type_elem.text
			if event_type == "END":
				continue

			attributes_elem = event.find("Attributes")
			if attributes_elem is None:
				warnings.append(f"{event_type}: missing Attributes")
				continue

			attributes = {}
			for attr_elem in attributes_elem.findall("Attribute"):
				name = attr_elem.get("name")
				if name is None:
					continue
				attributes[name] = attr_elem.text

			validate_event(event_type, attributes, fill_spec, runtime_state, bounds, errors, warnings)

			for match_fields in fill_spec.get_source_match_fields(event_type):
				runtime_state.record(event_type, attributes, match_fields)

			event_count += 1
	else:
		for event in list(root):
			if not isinstance(event.tag, str):
				continue
			event_type = event.tag
			if event_type == "END":
				continue

			attributes = {}
			for attr_elem in event:
				if not isinstance(attr_elem.tag, str):
					continue
				attributes[attr_elem.tag] = attr_elem.text

			validate_event(event_type, attributes, fill_spec, runtime_state, bounds, errors, warnings)

			for match_fields in fill_spec.get_source_match_fields(event_type):
				runtime_state.record(event_type, attributes, match_fields)

			event_count += 1

	print(f"Validated {event_count} events")
	print(f"Errors: {len(errors)}")
	print(f"Warnings: {len(warnings)}")
	for message in errors[:50]:
		print(f"ERROR: {message}")
	for message in warnings[:50]:
		print(f"WARN: {message}")


if __name__ == "__main__":
	main()
