"""Validate that filled skeletons follow the distributions declared in fill_spec.yaml.

This validator supports the distribution styles used by the bike examples:

- `old_new`: first-seen values count as new, repeated values count as old.
- `categorical`: explicit weights per value.
- `top_fraction_share`: the top fraction of distinct values should account for a
  target share of the samples.
- `uniform_over_column`: values should be spread roughly uniformly across the
  observed distinct values.
- `random`: acknowledged but not checked directly.

The script accepts both `--filled` and `--skeletons` for compatibility.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import Counter

from generator import FillSpec


def is_null(value):
    return value is None or str(value).startswith("NULL")


def parse_distribution(rule, event_type, attr_name):
    dist = rule.get("distribution")
    if dist is None:
        return None

    if isinstance(dist, str):
        dist_type = dist.strip().lower()
        if dist_type == "random":
            return {"type": "random"}
        raise ValueError(f"{event_type}.{attr_name}: unknown distribution '{dist}'")

    if not isinstance(dist, dict):
        raise ValueError(f"{event_type}.{attr_name}: distribution must be a string or map")

    dist_type = dist.get("type") or dist.get("mode")
    if dist_type is None and ("old" in dist or "new" in dist):
        dist_type = "old_new"

    if dist_type is None:
        raise ValueError(f"{event_type}.{attr_name}: distribution missing type")

    dist_type = str(dist_type).strip().lower()
    if dist_type == "random":
        return {"type": "random"}

    if dist_type in {"old_new", "old-new", "oldnew"}:
        old_value = dist.get("old")
        new_value = dist.get("new")
        if old_value is None or new_value is None:
            raise ValueError(
                f"{event_type}.{attr_name}: old_new distribution requires old and new"
            )
        old_ratio = float(old_value)
        new_ratio = float(new_value)
        total = old_ratio + new_ratio
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"{event_type}.{attr_name}: old+new must equal 1.0 (got {total})"
            )
        return {"type": "old_new", "old": old_ratio, "new": new_ratio}

    if dist_type in {"categorical", "category", "categories"}:
        weights = dist.get("weights") or dist.get("values")
        if not isinstance(weights, dict) or not weights:
            raise ValueError(
                f"{event_type}.{attr_name}: categorical distribution requires weights map"
            )
        parsed = {}
        for key, value in weights.items():
            parsed[str(key)] = float(value)
        total = sum(parsed.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"{event_type}.{attr_name}: categorical weights must sum to 1.0 (got {total})"
            )
        return {
            "type": "categorical",
            "weights": parsed,
            "bucket_by": dist.get("bucket_by"),
        }

    if dist_type in {"top_fraction_share", "top-fraction-share"}:
        top_fraction = dist.get("top_fraction")
        top_share = dist.get("top_share")
        if top_fraction is None or top_share is None:
            raise ValueError(
                f"{event_type}.{attr_name}: top_fraction_share requires top_fraction and top_share"
            )
        return {
            "type": "top_fraction_share",
            "top_fraction": float(top_fraction),
            "top_share": float(top_share),
        }

    if dist_type == "uniform_over_column":
        return {
            "type": "uniform_over_column",
            "table": dist.get("table"),
            "column": dist.get("column"),
            "where": dist.get("where"),
        }

    raise ValueError(f"{event_type}.{attr_name}: unknown distribution type '{dist_type}'")


def load_observations(skeletons_path):
    tree = ET.parse(skeletons_path)
    root = tree.getroot()
    observations = {}
    for event in root.findall("Event"):
        type_elem = event.find("Type")
        attrs_elem = event.find("Attributes")
        if type_elem is None or attrs_elem is None or type_elem.text is None:
            continue
        event_type = type_elem.text
        bucket = observations.setdefault(event_type, {})
        for attr_elem in attrs_elem.findall("Attribute"):
            name = attr_elem.get("name")
            if name is None:
                continue
            bucket.setdefault(name, []).append(attr_elem.text)
    return observations


def normalize_old_new(values):
    seen = set()
    counts = Counter()
    n_total = 0
    n_null = 0
    for value in values:
        if is_null(value):
            n_null += 1
            continue
        text_value = str(value)
        if text_value in seen:
            counts["old"] += 1
        else:
            counts["new"] += 1
            seen.add(text_value)
        n_total += 1
    return counts, n_total, n_null


def bucket_value(raw_value, bucket_spec):
    if bucket_spec is None:
        return str(raw_value)

    kind = bucket_spec.get("kind")
    if kind == "db_membership":
        seeded_max = bucket_spec.get("seeded_max_user_id")
        if seeded_max is None or raw_value is None:
            return None
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return None
        return "existing" if value <= int(seeded_max) else "new"

    return str(raw_value)


def normalize_categorical(values, bucket_spec=None):
    counts = Counter()
    n_total = 0
    n_null = 0
    for value in values:
        if is_null(value):
            n_null += 1
            continue
        bucketed = bucket_value(value, bucket_spec)
        if bucketed is None:
            n_null += 1
            continue
        counts[str(bucketed)] += 1
        n_total += 1
    return counts, n_total, n_null


def normalize_uniform(values):
    counts = Counter()
    n_total = 0
    n_null = 0
    for value in values:
        if is_null(value):
            n_null += 1
            continue
        counts[str(value)] += 1
        n_total += 1
    return counts, n_total, n_null


def normalize_top_fraction(values, top_fraction):
    counts = Counter()
    n_total = 0
    n_null = 0
    for value in values:
        if is_null(value):
            n_null += 1
            continue
        counts[str(value)] += 1
        n_total += 1

    unique_count = len(counts)
    top_count = max(1, int(round(unique_count * float(top_fraction)))) if unique_count else 0
    sorted_counts = sorted(counts.values(), reverse=True)
    top_seen_share = (sum(sorted_counts[:top_count]) / n_total) if n_total else 0.0
    return counts, n_total, n_null, top_seen_share, unique_count


def parse_args():
    parser = argparse.ArgumentParser(description="Validate value distributions in filled skeletons.")
    parser.add_argument("--fill-spec", required=True, help="Path to fill_spec.yaml")
    parser.add_argument("--filled", help="Path to filled skeletons.xml")
    parser.add_argument("--skeletons", help="Alias for --filled")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="Allowed deviation from expected ratio (default: 0.05)",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=30,
        help="Minimum samples before enforcing ratios (default: 30)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    skeletons_path = args.filled or args.skeletons
    if not skeletons_path:
        raise SystemExit("Either --filled or --skeletons is required")

    fill_spec = FillSpec(args.fill_spec)
    observations = load_observations(skeletons_path)

    checked = 0
    errors = []
    warnings = []

    for event_type, event_rules in fill_spec._spec.get("events", {}).items():
        for attr_name, rule in (event_rules or {}).items():
            if rule.get("category") in {"lookup", "copy"}:
                continue

            raw_dist = rule.get("distribution") or {}
            dist = parse_distribution(rule, event_type, attr_name)
            if dist is None or dist.get("type") == "random":
                continue

            values = observations.get(event_type, {}).get(attr_name, [])
            if not values:
                warnings.append(f"{event_type}.{attr_name}: no observations found")
                continue

            tolerance = float(raw_dist.get("tolerance", args.tolerance))

            dtype = dist["type"]
            if dtype == "old_new":
                counts, n_total, _n_null = normalize_old_new(values)
                expected_new = dist["new"]
                actual_new = (counts["new"] / n_total) if n_total else 0.0
                print(
                    f"STAT: {event_type}.{attr_name}: new {actual_new:.3f} "
                    f"(expected {expected_new:.3f}) samples {n_total}"
                )
                if n_total >= args.min_samples and abs(actual_new - expected_new) > tolerance:
                    errors.append(
                        f"{event_type}.{attr_name}: new ratio {actual_new:.3f} outside {expected_new:.3f} +/- {tolerance:.3f}"
                    )
                checked += 1
                continue

            if dtype == "categorical":
                counts, n_total, _n_null = normalize_categorical(values, dist.get("bucket_by"))
                print(f"STAT: {event_type}.{attr_name}: categorical samples {n_total}")
                for value_key, expected_ratio in dist["weights"].items():
                    actual_ratio = (counts.get(value_key, 0) / n_total) if n_total else 0.0
                    if n_total >= args.min_samples and abs(actual_ratio - expected_ratio) > tolerance:
                        errors.append(
                            f"{event_type}.{attr_name}: value {value_key} ratio {actual_ratio:.3f} outside {expected_ratio:.3f} +/- {tolerance:.3f}"
                        )
                checked += 1
                continue

            if dtype == "uniform_over_column":
                counts, n_total, _n_null = normalize_uniform(values)
                unique_count = len(counts)
                print(
                    f"STAT: {event_type}.{attr_name}: uniform_over_column samples {n_total} unique {unique_count}"
                )
                if unique_count == 0:
                    warnings.append(f"{event_type}.{attr_name}: no distinct values found")
                    continue
                expected_ratio = 1.0 / unique_count
                for value_key, observed_count in counts.items():
                    actual_ratio = observed_count / n_total if n_total else 0.0
                    if n_total >= args.min_samples and abs(actual_ratio - expected_ratio) > tolerance:
                        errors.append(
                            f"{event_type}.{attr_name}: value {value_key} ratio {actual_ratio:.3f} outside {expected_ratio:.3f} +/- {tolerance:.3f}"
                        )
                checked += 1
                continue

            if dtype == "top_fraction_share":
                _counts, n_total, _n_null, actual_top_share, unique_count = normalize_top_fraction(
                    values, dist["top_fraction"]
                )
                expected_top_share = dist["top_share"]
                print(
                    f"STAT: {event_type}.{attr_name}: top share {actual_top_share:.3f} "
                    f"(expected {expected_top_share:.3f}) unique {unique_count} samples {n_total}"
                )
                if n_total >= args.min_samples and abs(actual_top_share - expected_top_share) > tolerance:
                    errors.append(
                        f"{event_type}.{attr_name}: top share {actual_top_share:.3f} outside {expected_top_share:.3f} +/- {tolerance:.3f}"
                    )
                checked += 1
                continue

            warnings.append(f"{event_type}.{attr_name}: unsupported distribution type {dtype}")

    print(f"Checked {checked} distributions")
    print(f"Errors: {len(errors)}")
    print(f"Warnings: {len(warnings)}")
    for message in errors[:50]:
        print(f"ERROR: {message}")
    for message in warnings[:50]:
        print(f"WARN: {message}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
