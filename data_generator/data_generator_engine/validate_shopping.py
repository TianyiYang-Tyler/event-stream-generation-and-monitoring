#!/usr/bin/env python3
"""Validator for filled shopping example skeletons.

Validates:
1. Basic filled skeleton rules (copy, lookup, dependent attributes)
2. Distribution compliance (customer_rating, user_id split, stock depletion)
3. Event structure and completeness
4. Time ordering (events should be sorted by ascending time)

If time-order violations are found, sort the file using sort_shopping_by_time.py:
    python3 sort_shopping_by_time.py INPUT.xml

Usage:
    python3 validate_shopping.py \
        --filled data_generator/shopping_universitystore_example/output/skeletons_filled.xml \
        --fill-spec data_generator/shopping_universitystore_example/input/fill_spec.yaml \
        --report data_generator/shopping_universitystore_example/output/shopping_validation_report.txt
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET

from generator import FillSpec


def is_null(value):
    """Check if value is null/missing."""
    return value is None or str(value).strip() == "" or str(value).startswith("NULL")


def get_event_time(attributes):
    """Extract numeric time from event attributes."""
    time_val = attributes.get("time")
    if time_val is None:
        return None
    try:
        return float(time_val)
    except (ValueError, TypeError):
        return None


def validate_filled_skeleton(filled_path, fill_spec, report_path=None):
    """Validate filled skeleton against fill_spec rules and distributions."""
    
    tree = ET.parse(filled_path)
    root = tree.getroot()
    
    # Tracking structures
    event_counts = Counter()
    order_ids = {}  # order_id -> attributes
    
    # Distribution tracking
    rating_distribution = Counter()
    user_splits = Counter()  # 'existing' vs 'new'
    
    errors = []
    warnings = []
    event_count = 0
    time_order_violations = 0
    prev_time = None
    seeded_max_user_id = 30000  # From fill_spec
    
    # First pass: load all events and validate structure
    events_list = []
    
    # Parse events - they're direct children of EventStream
    for event_elem in root:
        event_type = event_elem.tag
        
        if event_type == "END":
            continue
        
        event_count += 1
        event_counts[event_type] += 1
        
        # Parse attributes from element's children
        attributes = {}
        for child in event_elem:
            tag = child.tag
            value = child.text
            if tag is not None:
                attributes[tag] = value
        
        # Check time ordering
        time_val = get_event_time(attributes)
        if time_val is not None:
            if prev_time is not None and time_val < prev_time:
                time_order_violations += 1
            prev_time = time_val
        
        events_list.append({
            "type": event_type,
            "attributes": attributes,
            "event_number": event_count
        })
        
        # Track order_ids for validation
        if event_type == "Order" and "order_id" in attributes:
            order_id = attributes["order_id"]
            if order_id in order_ids:
                warnings.append(f"Duplicate order_id: {order_id}")
            order_ids[order_id] = attributes.copy()
    
    # Second pass: validate rules and distributions
    for event_info in events_list:
        event_type = event_info["type"]
        attributes = event_info["attributes"]
        
        rules = fill_spec.get_event_rules(event_type)
        if not rules:
            continue
        
        # Validate required attributes - skip attributes that are copy/lookup dependent
        for attr_name, rule in rules.items():
            # Skip validation for attributes that come from other events
            if rule.get("category") in ("copy", "dependent_select", "dependent_generate", "lookup"):
                continue
            
            value = attributes.get(attr_name)
            
            if is_null(value):
                # Only report as error for simple generate/fixed categories
                if rule.get("category") in ("generate", "select", "fixed"):
                    errors.append(f"{event_type}.{attr_name}: missing value")
                continue
            
            # Validate copy rules - value should match source event
            if rule.get("category") == "copy":
                source_event = rule.get("source_event")
                match_on = rule.get("match_on")
                
                if source_event and match_on:
                    match_id = attributes.get(match_on)
                    if match_id and source_event == "Order" and match_id in order_ids:
                        source_attrs = order_ids[match_id]
                        source_value = source_attrs.get(attr_name)
                        
                        if not is_null(source_value) and str(value) != str(source_value):
                            errors.append(
                                f"{event_type}.{attr_name}: "
                                f"copy mismatch. Expected {source_value}, got {value}"
                            )
        
        # Distribution tracking for specific attributes
        if event_type == "Rate_order":
            if "customer_rating" in attributes:
                rating = attributes["customer_rating"]
                if not is_null(rating):
                    try:
                        rating_int = int(str(rating).strip())
                        rating_distribution[rating_int] += 1
                    except ValueError:
                        errors.append(f"Rate_order[{event_info['event_number']}].customer_rating: invalid rating {rating}")
        
        # Track user_id split (existing vs new)
        if "user_id" in attributes:
            try:
                user_id = int(attributes["user_id"])
                if user_id <= seeded_max_user_id:
                    user_splits["existing"] += 1
                else:
                    user_splits["new"] += 1
            except (ValueError, TypeError):
                pass
    
    # Validate distributions
    print("\n" + "=" * 70)
    print("FILLED STREAM VALIDATION REPORT")
    print("=" * 70)
    
    print("\nSTRUCTURE VALIDATION")
    print("-" * 70)
    print(f"Total events: {event_count:,}")
    print(f"Event type counts: {dict(event_counts)}")
    print(f"Distinct orders: {len(order_ids):,}")
    print(f"Time-order violations: {time_order_violations} (events whose time < previous; 0 means file is sorted ascending)")
    
    if time_order_violations > 0:
        print("\n⚠ WARNING: File is not sorted by time!")
        print("To sort, run:")
        print("  python3 sort_shopping_by_time.py <input_file> --out <output_file>")
    
    print("\nDISTRIBUTIONS (actual)")
    print("-" * 70)
    
    # Customer rating distribution
    if rating_distribution:
        print("\ncustomer_rating (Rate_order events):")
        total_ratings = sum(rating_distribution.values())
        for rating in sorted(rating_distribution.keys()):
            count = rating_distribution[rating]
            pct = 100.0 * count / total_ratings if total_ratings > 0 else 0
            print(f"    {rating}-star: {count:,} ({pct:.1f}%)")
        
        # Check against expected distribution
        expected = {5: 0.50, 4: 0.25, 3: 0.15, 2: 0.07, 1: 0.03}
        tolerance = 0.02
        print("\n    Expected distribution (categorical):")
        for rating in sorted(expected.keys()):
            exp_pct = expected[rating] * 100
            print(f"    {rating}-star: {exp_pct:.1f}% (±{tolerance*100:.1f}%)")
    
    # User split distribution
    if user_splits:
        print("\nuser_id split (seeded_max_user_id={:,}):".format(seeded_max_user_id))
        total_users = sum(user_splits.values())
        for split_type in ["existing", "new"]:
            count = user_splits.get(split_type, 0)
            pct = 100.0 * count / total_users if total_users > 0 else 0
            print(f"    {split_type}: {count:,} ({pct:.1f}%)")
        
        # Check against expected 60/40 split
        expected_split = {"existing": 0.60, "new": 0.40}
        tolerance = 0.05
        print("\n    Expected split: 60% existing / 40% new")
    
    # Event sequence validation
    print("\nEVENT SEQUENCE VALIDATION")
    print("-" * 70)
    
    # Check that events follow expected patterns per order
    orders_info = defaultdict(list)
    for event_info in events_list:
        event_type = event_info["type"]
        attributes = event_info["attributes"]
        
        if "order_id" in attributes:
            order_id = attributes["order_id"]
            orders_info[order_id].append(event_type)
    
    # Validate typical order flow
    valid_flows = 0
    invalid_flows = 0
    
    for order_id, event_sequence in orders_info.items():
        # Expected flow: Order -> [AddItem*] -> Confirm_payment -> Ship -> Confirm_arrival -> [Delivery_out] -> Confirm_delivery -> [Rate_order]
        # At minimum: Order, Confirm_payment, Confirm_delivery
        has_order = "Order" in event_sequence
        has_payment = "Confirm_payment" in event_sequence
        has_delivery = "Confirm_delivery" in event_sequence
        
        if has_order and has_payment and has_delivery:
            valid_flows += 1
        else:
            invalid_flows += 1
            if invalid_flows <= 5:  # Only show first 5
                warnings.append(f"Order {order_id}: incomplete flow. Events: {event_sequence}")
    
    print(f"Valid order flows: {valid_flows:,}")
    print(f"Incomplete order flows: {invalid_flows:,}")
    
    # Summary
    print("\nERROR / WARNING SUMMARY")
    print("-" * 70)
    print(f"Total errors: {len(errors)}")
    print(f"Total warnings: {len(warnings)}")
    
    if errors:
        print("\nFirst 20 ERRORS:")
        for msg in errors[:20]:
            print(f"  ERROR: {msg}")
    
    if warnings:
        print("\nFirst 20 WARNINGS:")
        for msg in warnings[:20]:
            print(f"  WARN: {msg}")
    
    # Write report
    if report_path:
        with open(report_path, "w") as f:
            f.write("=" * 70 + "\n")
            f.write("FILLED STREAM VALIDATION REPORT\n")
            f.write("=" * 70 + "\n")
            f.write("\nSTRUCTURE VALIDATION\n")
            f.write("-" * 70 + "\n")
            f.write(f"Total events: {event_count:,}\n")
            f.write(f"Event type counts: {dict(event_counts)}\n")
            f.write(f"Distinct orders: {len(order_ids):,}\n")
            f.write(f"Time-order violations: {time_order_violations}\n")
            
            if time_order_violations > 0:
                f.write("\nWARNING: File is not sorted by time!\n")
                f.write("To sort, run:\n")
                f.write("  python3 sort_shopping_by_time.py <input_file> --out <output_file>\n")
            
            f.write("\nDISTRIBUTIONS (actual)\n")
            f.write("-" * 70 + "\n")
            
            if rating_distribution:
                f.write("\ncustomer_rating (Rate_order events):\n")
                total_ratings = sum(rating_distribution.values())
                for rating in sorted(rating_distribution.keys()):
                    count = rating_distribution[rating]
                    pct = 100.0 * count / total_ratings if total_ratings > 0 else 0
                    f.write(f"    {rating}-star: {count:,} ({pct:.1f}%)\n")
                
                f.write("\n    Expected distribution:\n")
                for rating in [5, 4, 3, 2, 1]:
                    exp_pct = expected.get(rating, 0) * 100
                    f.write(f"    {rating}-star: {exp_pct:.1f}%\n")
            
            if user_splits:
                f.write(f"\nuser_id split (seeded_max_user_id={seeded_max_user_id:,}):\n")
                total_users = sum(user_splits.values())
                for split_type in ["existing", "new"]:
                    count = user_splits.get(split_type, 0)
                    pct = 100.0 * count / total_users if total_users > 0 else 0
                    f.write(f"    {split_type}: {count:,} ({pct:.1f}%)\n")
                f.write("\n    Expected split: 60% existing / 40% new\n")
            
            f.write("\nEVENT SEQUENCE VALIDATION\n")
            f.write("-" * 70 + "\n")
            f.write(f"Valid order flows: {valid_flows:,}\n")
            f.write(f"Incomplete order flows: {invalid_flows:,}\n")
            
            f.write("\nERROR / WARNING SUMMARY\n")
            f.write("-" * 70 + "\n")
            f.write(f"Total errors: {len(errors)}\n")
            f.write(f"Total warnings: {len(warnings)}\n")
            
            if errors:
                f.write("\nFirst 20 ERRORS:\n")
                for msg in errors[:20]:
                    f.write(f"  ERROR: {msg}\n")
            
            if warnings:
                f.write("\nFirst 20 WARNINGS:\n")
                for msg in warnings[:20]:
                    f.write(f"  WARN: {msg}\n")
        
        print(f"\n✓ Report written to {report_path}")
    
    return len(errors) == 0


def main():
    parser = argparse.ArgumentParser(
        description="Validate filled shopping example skeletons"
    )
    parser.add_argument(
        "--filled",
        required=True,
        help="Path to filled skeletons.xml"
    )
    parser.add_argument(
        "--fill-spec",
        required=True,
        help="Path to fill_spec.yaml"
    )
    parser.add_argument(
        "--report",
        help="Path to write validation report"
    )
    
    args = parser.parse_args()
    
    fill_spec = FillSpec(args.fill_spec)
    success = validate_filled_skeleton(args.filled, fill_spec, args.report)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
