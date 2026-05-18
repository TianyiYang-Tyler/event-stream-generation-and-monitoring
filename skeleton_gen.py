import random
from collections import deque
import xmltodict
import xml.etree.ElementTree as ET
import math

from helpers import *

import heapq
import itertools

def generate_instance(
    edges_by_source,
    events,
    event_refs,
    start_time,
    auto_counters,
    raw_schema, 
    termination_rules=None
):
    """
    3-layer simulation model

    Layers:
        1. EVENT STREAM
        2. RULE SCHEDULER
        3. TERMINATION CONTROLLER

    Core invariant:
        Once a termination activates, affected rules are removed
        from future scheduling entirely.
    """

    # =========================================================
    # STATE
    # =========================================================
    state = {
        "event_counts": {},
        "events": [],
        "event_instances": {},
        "null_counter": 0,
        "events_schema": events,
        "auto_counters": auto_counters,
        "instance_values": {},
        "canonical_parents": {},
        "table_null_pool": {}
    }

    # =========================================================
    # TERMINATION ENGINE
    # =========================================================
    termination_state = []

    if termination_rules:
        for rule in termination_rules:

            srcs = rule["source"]

            if isinstance(srcs, str):
                srcs = [srcs]

            tgts = rule["terminator"]

            # normalize ALL
            if tgts == ["ALL"]:
                tgts = "ALL"

            elif isinstance(tgts, str):

                if tgts != "ALL":
                    tgts = [tgts]

            termination_state.append({
                "sources": set(srcs),
                "seen": set(),
                "targets": tgts,
                "active": False,
                "termination_time": None
            })

    # =========================================================
    # RULE REGISTRY
    # =========================================================
    active_rule_ids = set()

    for src, edge_list in edges_by_source.items():
        for edge in edge_list:
            active_rule_ids.add(edge["rule_id"])

    # =========================================================
    # START EVENT
    # =========================================================
    start_event = {
        "type": "START",
        "time": start_time - 1,
        "attrs": {},
        "source_rule_id": "START"
    }

    state["events"].append(start_event)
    state["event_instances"]["START"] = [start_event]

    # =========================================================
    # RULE EXECUTION HEAP
    # =========================================================
    #
    # heap item:
    #
    # (
    #     scheduled_time,
    #     insertion_counter,
    #     edge,
    #     trigger_event
    # )
    #
    # =========================================================
    work_heap = []

    counter = itertools.count()
    processed_termination_events = set()

    def push_rule(edge, trigger_event, scheduled_time):

        if edge["rule_id"] not in active_rule_ids:
            return

        heapq.heappush(
            work_heap,
            (
                scheduled_time,
                next(counter),
                edge,
                trigger_event
            )
        )

    # seed START
    for edge in edges_by_source.get("START", []):
        push_rule(edge, start_event, start_event["time"])

    # =========================================================
    # TERMINATION HELPERS
    # =========================================================
    def activate_terminations(evt):

        evt_type = evt["type"]
        evt_time = evt["time"]

        for term in termination_state:

            if term["active"]:
                continue

            if evt_type in term["sources"]:
                term["seen"].add(evt_type)

            if term["sources"].issubset(term["seen"]):

                term["active"] = True
                term["termination_time"] = evt_time

                # ---------------------------------------------
                # RULE-LEVEL DEACTIVATION
                # ---------------------------------------------
                targets = term["targets"]

                if targets == "ALL":
                    # Don't clear rules — event_blocked() enforces the time cutoff.
                    # Only record termination_time so event_blocked() can filter by timestamp.
                    return

                # TERMINATE specific event generators
                for src, edges in edges_by_source.items():

                    for edge in edges:

                        if any(
                            tgt in targets
                            for tgt in edge["TARGET"]
                        ):
                            active_rule_ids.discard(
                                edge["rule_id"]
                            )

    def event_blocked(event_type, event_time):

        for term in termination_state:

            if not term["active"]:
                continue

            cutoff = term["termination_time"]

            if cutoff is not None and event_time >= cutoff:

                if term["targets"] == "ALL":
                    return True

                if event_type in term["targets"]:
                    return True

        return False

    # =========================================================
    # MAIN LOOP
    # =========================================================
    while work_heap:

        _, _, edge, trigger_evt = heapq.heappop(work_heap)
        # =====================================================
        # CHRONOLOGICAL TERMINATION ACTIVATION
        # =====================================================
        evt_key = (
            trigger_evt["type"],
            trigger_evt["time"],
            id(trigger_evt)
        )

        if evt_key not in processed_termination_events:

            activate_terminations(trigger_evt)

            processed_termination_events.add(evt_key)

        # GLOBAL TERMINATION — check if ALL termination has fired and we're past its time
        all_terminated = any(
            term["active"] and term["targets"] == "ALL"
            for term in termination_state
        )
        # Don't break immediately — let event_blocked() handle time filtering.
        # Only break if the heap only contains events past the cutoff (handled naturally).

        # rule already terminated
        if edge["rule_id"] not in active_rule_ids:
            continue

        # =====================================================
        # BUILD PARENTS
        # =====================================================
        parent_events = {}

        for src in edge["SOURCE"]:

            if src == "START":
                parent_events[src] = start_event

            elif src == trigger_evt["type"]:
                parent_events[src] = trigger_evt

        if any(
            src not in parent_events
            for src in edge["SOURCE"]
        ):
            continue

        parent_time = max(
            evt["time"]
            for evt in parent_events.values()
        )

        # =====================================================
        # SAMPLE COUNT
        # =====================================================
        count_dist = edge.get("count_dist")
        if count_dist is None:
            count = 1
        else:
            count = sample_count(count_dist)
        for _ in range(count):

            for tgt in edge["TARGET"]:

                # =================================================
                # SAMPLE TIME
                # =================================================
                time_dist = edge.get("time_dist")

                if time_dist is None:
                    delay = 1
                else:
                    delay = sample_time(time_dist)

                event_time = parent_time + delay

                # =================================================
                # TERMINATION FILTER
                # =================================================
                if event_blocked(tgt, event_time):
                    continue

                # =================================================
                # BUILD ATTRIBUTES
                # =================================================
                attrs = build_attributes(tgt, state, parent_events, event_refs, raw_schema)

                evt = {
                    "type": tgt,
                    "time": event_time,
                    "attrs": attrs,
                    "source_rule_id": edge["rule_id"]
                }

                # =================================================
                # STORE EVENT
                # =================================================
                state["events"].append(evt)
                # ✅ ADD THIS — activate terminations on emission, not just on pop
                activate_terminations(evt)

                state["event_counts"][tgt] = (
                    state["event_counts"].get(tgt, 0) + 1
                )

                state["event_instances"].setdefault(
                    tgt,
                    []
                ).append(evt)

                if tgt not in state["canonical_parents"]:
                    state["canonical_parents"][tgt] = evt

                # =================================================
                # RULE SCHEDULING
                # =================================================
                if active_rule_ids:

                    for next_edge in edges_by_source.get(tgt, []):

                        push_rule(next_edge, evt, event_time)

    # =========================================================
    # FINAL SORT
    # =========================================================
    state["events"].sort(
        key=lambda x: x["time"]
    )

    return state["events"]


def generate_event_stream_to_xml(
    edges_by_source,
    events,
    event_refs,
    distributions,
    start,
    end,
    output_file
):

    import xml.etree.ElementTree as ET
    import random

    root = ET.Element("EventStream")

    # 🔥 NEW: global AUTO_INCREMENT counters
    auto_counters = {}
    for evt in event_refs:
        if "AUTO_INCREMENT" in event_refs[evt]:
            for attr in event_refs[evt]["AUTO_INCREMENT"]:
                auto_counters[attr] = 0

    # find START distribution
    start_dist = None
    for d in distributions:
        if d["type"] == "start_distribution":
            start_dist = d
            break

    if not start_dist:
        raise ValueError("Missing START distribution")

    # iterate buckets (correct interpretation)
    for bucket in start_dist["distribution"]:

        start_h = int(bucket["distribution_range"]["start"])
        end_h   = int(bucket["distribution_range"]["end"])
        count   = int(bucket["value"])
        ratio = int(start_dist["ratio"])
        start = int(start)

        start_t = int(start + start_h * start_dist["ratio"])
        end_t   = int(start + end_h   * start_dist["ratio"])

        for _ in range(count):

            base_time = random.randrange(start_t, end_t)

            instance = generate_instance(
                edges_by_source,
                events,
                refs,
                base_time,
                auto_counters,
                termination_rules
            )

            for evt in instance:
                if evt["type"] not in ("START", "END"):
                    event_to_xml(root, evt)

    tree = ET.ElementTree(root)
    tree.write(output_file, encoding="utf-8", xml_declaration=True)

def write_workflow_log(file, instance_events, enactment_id):

    # filter out START
    instance_events = [e for e in instance_events if e["type"] != "START"]

    instance_events.sort(key=lambda x: x["time"])

    for idx, evt in enumerate(instance_events, start=1):
        line = f"{int(evt['time'])} {enactment_id} {idx} {evt['type']}\n"
        file.write(line)

def generate_event_stream_outputs(
    edges_by_source,
    events,
    event_refs,
    distributions,
    start,
    end,
    xml_output,
    log_output,
    termination_rules=None,
    data_dict = None
):

    import xml.etree.ElementTree as ET
    import random

    root = ET.Element("EventStream")

    # open log file
    log_file = open(log_output, "w")

    # AUTO_INCREMENT counters (global)
    auto_counters = {}
    for evt in event_refs:
        if "AUTO_INCREMENT" in event_refs[evt]:
            for attr in event_refs[evt]["AUTO_INCREMENT"]:
                auto_counters[attr] = 0

    # find START distribution
    start_dist = None
    for d in distributions:
        if d["type"] == "start_distribution":
            start_dist = d
            break

    if not start_dist:
        raise ValueError("Missing START distribution")

    enactment_id = 0

    # iterate buckets
    for bucket in start_dist["distribution"]:

        start_h = int(bucket["distribution_range"]["start"])
        end_h   = int(bucket["distribution_range"]["end"])
        count   = int(bucket["value"])
        start = int(start)

        start_t = int(start + start_h * start_dist["ratio"])
        end_t   = int(start + end_h   * start_dist["ratio"])

        for _ in range(count):

            base_time = random.randrange(start_t, end_t)

            instance = generate_instance(
                edges_by_source, events, event_refs,
                base_time, auto_counters,
                raw_schema=data_dict['root']['event_type_definitions'],
                termination_rules=termination_rules
            )

            # --- XML ---
            for evt in instance:
                if evt["type"] not in ["START", "END"]:
                    event_to_xml(root, evt)

            # --- WORKFLOW LOG ---
            write_workflow_log(log_file, instance, enactment_id)

            enactment_id += 1

    # finalize XML
    tree = ET.ElementTree(root)
    tree.write(xml_output, encoding="utf-8", xml_declaration=True)

    # close log
    log_file.close()

def run_quick_test(
    edges_by_source,
    events,
    refs,
    distributions,
    start,
    auto_counters,
    num_instances,
    termination_rules=None,
    data_dict = None
):
    import random
    import copy

    # -----------------------------------------------------
    # FIND START DISTRIBUTION
    # -----------------------------------------------------
    start_dist = None

    for d in distributions:
        if d["type"] == "start_distribution":
            start_dist = d
            break

    if not start_dist:
        raise ValueError("Missing START distribution")

    print(f"\n=== QUICK TEST: {num_instances} INSTANCE(S) ===\n")

    # -----------------------------------------------------
    # GENERATE INSTANCES
    # -----------------------------------------------------
    for inst_id in range(num_instances):

        bucket = random.choice(
            start_dist["distribution"]
        )

        start_h = int(
            bucket["distribution_range"]["start"]
        )

        end_h = int(
            bucket["distribution_range"]["end"]
        )

        start_t = int(
            start + start_h * start_dist["ratio"]
        )

        end_t = int(
            start + end_h * start_dist["ratio"]
        )

        base_time = random.randrange(start_t, end_t)

        # IMPORTANT: do NOT deep copy — auto_counters must persist across instances
        instance = generate_instance(
            edges_by_source, events, refs,
            base_time, auto_counters,        # ← pass directly
            raw_schema=data_dict['root']['event_type_definitions'],
            termination_rules=termination_rules
        )

        # remove synthetic events
        instance = [
            e for e in instance
            if e["type"] not in ("START", "END")
        ]

        instance.sort(
            key=lambda x: x["time"]
        )

        print(f"\n--- Instance {inst_id + 1} ---")

        if not instance:
            print("(empty instance)")
            continue

        for i, evt in enumerate(instance, 1):

            print(
                f"{i:02d} | "
                f"t={evt['time']:5d} | "
                f"{evt['type']} | "
                f"rule={evt['source_rule_id']}"
            )

            for k, v in evt["attrs"].items():
                print(f"     {k}: {v}")

import argparse

def main():

    parser = argparse.ArgumentParser(description="Event stream generator")

    parser.add_argument(
        "--name",
        required=True,
        help="Base name of the input/output files (e.g. bike_rental)"
    )

    parser.add_argument(
        "--quick_test",
        nargs="?",
        const=1,
        type=int,
        help="Generate and print N instances instead of full stream"
    )

    args = parser.parse_args()

    # --------------------------------------------------
    # File paths derived from --name
    # --------------------------------------------------

    input_file = f"./output_xml/{args.name}_info.xml"

    xml_output = f"./output_xml/{args.name}_stream.xml"

    log_output = f"./{args.name}_log.txt"

    # --------------------------------------------------
    # Load input XML
    # --------------------------------------------------

    with open(input_file, 'r', encoding='utf-8') as file:
        data_dict = xmltodict.parse(file.read())

    # --------------------------------------------------
    # Build structures
    # --------------------------------------------------

    events = extract_events(data_dict)

    edges_dict = extract_event_edges(data_dict)

    refs = extract_event_refs(data_dict)

    dists = extract_distributions(data_dict)

    edge_objs = build_edges(edges_dict, dists)

    edges_by_source, termination_rules = build_edges_by_source(edge_objs)

    # --------------------------------------------------
    # Time range
    # --------------------------------------------------

    base = data_dict['root']['global_configurations']['base_time_granularity']

    start = int(time_conversion(
        data_dict['root']['global_configurations']['time_range']['start_time'],
        base
    ))

    end = int(time_conversion(
        data_dict['root']['global_configurations']['time_range']['end_time'],
        base
    ))

    # --------------------------------------------------
    # GLOBAL AUTO_INCREMENT counters
    # --------------------------------------------------

    auto_counters = {}

    for evt in refs:

        if "AUTO_INCREMENT" in refs[evt]:

            for attr in refs[evt]["AUTO_INCREMENT"]:

                auto_counters[attr] = 0

    # --------------------------------------------------
    # QUICK TEST MODE
    # --------------------------------------------------

    if args.quick_test is not None:

        run_quick_test(
            edges_by_source,
            events,
            refs,
            dists,
            start,
            auto_counters,
            num_instances=args.quick_test,
            termination_rules=termination_rules,
            data_dict = data_dict
        )

    # --------------------------------------------------
    # FULL GENERATION
    # --------------------------------------------------

    else:

        generate_event_stream_outputs(
            edges_by_source,
            events,
            refs,
            dists,
            start,
            end,
            xml_output,
            log_output,
            termination_rules=termination_rules,
            data_dict = data_dict
        )


if __name__ == "__main__":
    main()
