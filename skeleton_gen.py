import random
from collections import deque
import xmltodict
import xml.etree.ElementTree as ET
import math

def poisson(lam):
    L = math.exp(-lam)
    k = 0
    p = 1

    while p > L:
        k += 1
        p *= random.random()

    return k - 1

def create_xml_root():
    root = ET.Element("EventStream")
    return root

def event_to_xml(parent, event):
    evt_elem = ET.SubElement(parent, "Event")

    ET.SubElement(evt_elem, "Type").text = event["type"]
    ET.SubElement(evt_elem, "Time").text = str(event["time"])
    ET.SubElement(evt_elem, "SourceRule").text = event["source_rule_id"]

    attrs_elem = ET.SubElement(evt_elem, "Attributes")

    for k, v in event["attrs"].items():
        attr_elem = ET.SubElement(attrs_elem, "Attribute", name=k)
        attr_elem.text = str(v)

def unit_to_ratio(unit):
    unit = unit.upper()
    if unit in ['MICROSECOND', 'MS']:
        return 1
    elif unit in ['SECOND', 'SEC']:
        return 1e6
    elif unit in ['MINUTE', 'MIN']:
        return 6 * 1e7
    elif unit == 'HOUR':
        return 3.6 * 1e9
    elif unit == 'DAY':
        return 8.64 * 1e10
    else:
        return -1

def time_conversion(org, base_time_granularity):
    if org['unit'] == 'DEFAULT':
        return int(org['value'])   # 🔥 FIX: cast to int

    if (unit_to_ratio(org['unit']) * int(org['value'])) % (
        unit_to_ratio(base_time_granularity['unit']) * int(base_time_granularity['value'])
    ) != 0:
        raise ValueError(f"{org} violates base granularity constraint!")

    return int(
        (unit_to_ratio(org['unit']) * int(org['value'])) /
        (unit_to_ratio(base_time_granularity['unit']) * int(base_time_granularity['value']))
    )

def extract_events(data):
    events = {}

    for event in data['root']['event_type_definitions']:
        name = event['event_name']
        attrs = [attr['attribute_name'] for attr in event['attributes']]
        events[name] = attrs

    return events

def extract_event_edges(data):
    edges = {}

    for rule in data['root']['process_schema']:

        if rule['type'] == 'START':
            rule_id = rule['rule_id']
            edges[rule_id] = {
                "SOURCE": ["START"],
                "TARGET": [rule['target_events']['event_name']]
            }

        elif rule['type'] == 'CAUSE':
            rule_id = rule['rule_id']
            source = rule['source_events']
            target = rule['target_event']['event_name']

            edges[rule_id] = {
                "SOURCE": [source] if isinstance(source, str) else source,
                "TARGET": [target]
            }

        else: # TERMINATE
            source = rule['source_events']
            target = rule['target_event']
            if 'TERMINATE' not in edges:
            	edges['TERMINATE'] = []
            edges['TERMINATE'].append( {
                "SOURCE": [source] if isinstance(source, str) else source,
                "TARGET": [target]
            } )

    return edges

def extract_event_refs(data):
    refs = {}

    for event in data['root']['event_type_definitions']:
        event_name = event['event_name']
        refs[event_name] = {}

        for attr in event['attributes']:
            attr_name = attr['attribute_name']
            attr_type = attr['attribute_type']

            # normalize
            if isinstance(attr_type, str):
                attr_type = {'type': attr_type}

            t = attr_type.get('type')

            if t == 'event_reference':
                src_event = attr_type['event_name']
                src_attr = attr_type['event_values']

                refs.setdefault(event_name, {})
                refs[event_name].setdefault(src_event, {})
                refs[event_name][src_event][attr_name] = src_attr

            elif t == 'AUTO_INCREMENT':
                refs.setdefault(event_name, {})
                refs[event_name].setdefault("AUTO_INCREMENT", {})
                refs[event_name]["AUTO_INCREMENT"][attr_name] = 0

            # ✅ IMPORTANT: DO NOTHING for global_restricted
            # it should NOT appear in refs at all

    return refs

def sample_from_distribution(dist):
    weights = [int(d['value']) for d in dist]
    choices = list(range(len(dist)))

    idx = random.choices(choices, weights=weights, k=1)[0]
    chosen = dist[idx]['distribution_range']

    start = int(chosen['start'])
    end = int(chosen['end'])

    return random.randrange(start, end)  # right exclusive

def extract_distributions(data):
    results = []

    base = data['root']['global_configurations']['base_time_granularity']

    # --- 1. event_distributions ---
    for dist in data['root'].get('event_distributions', []):
        results.append({
            "rule_id": dist['rule_id'],  # NOTE: it's event_name, not rule_id
            "type": dist['type'],
            "ratio": time_conversion(dist['base_time_granularity_value'], base),
            "distribution": dist['distribution']
        })

    # --- 2. process_schema conditions ---
    for rule in data['root']['process_schema']:

        # skip rules without rule_id (e.g., TERMINATE safety)
        rule_id = rule.get('rule_id')
        if not rule_id:
            continue

        if rule['type'] != 'CAUSE':
            continue

        target = rule.get('target_event', {})

        # -------- TIME CONDITION --------
        tc = target.get('time_condition')
        if tc:
            if tc['type'] == 'EXACTLY':
                val = time_conversion(tc['time'], base)
                results.append({
                    "rule_id": rule_id,
                    "type": "TIME_EXACTLY",
                    "value": val
                })

            elif tc['type'] == 'RANGE':
                start = time_conversion(tc['start_time'], base)
                end = time_conversion(tc['end_time'], base)
                results.append({
                    "rule_id": rule_id,
                    "type": "TIME_RANGE",
                    "start": start,
                    "end": end
                })

        # -------- COUNT CONDITION --------
        cc = target.get('count_condition')
        if cc:
            if cc['type'] == 'EXACTLY':
                results.append({
                    "rule_id": rule_id,
                    "type": "COUNT_EXACTLY",
                    "value": int(cc['count'])
                })

            elif cc['type'] == 'RANGE':
                results.append({
                    "rule_id": rule_id,
                    "type": "COUNT_RANGE",
                    "start": int(cc['start']),
                    "end": int(cc['end'])
                })

    return results

data_dict = {}
# From a file
with open('output_xml/bike_rental_info.xml', 'r', encoding='utf-8') as file:
    data_dict = xmltodict.parse(file.read())

base_time_granularity = data_dict['root']['global_configurations']['base_time_granularity']
start, end = time_conversion(data_dict['root']['global_configurations']['time_range']['start_time'], base_time_granularity), time_conversion(data_dict['root']['global_configurations']['time_range']['end_time'], base_time_granularity)

#print(data_dict)
#print(extract_events(data_dict))
#print(extract_event_refs(data_dict))
#print(extract_event_edges(data_dict))
#print(extract_distributions(data_dict))
#print(sample_from_distribution(extract_distributions(data_dict)))

def build_edges(edges_dict, distributions):
    dist_map = {}

    # group distributions by rule_id
    for d in distributions:
        rid = d['rule_id']
        if rid not in dist_map:
            dist_map[rid] = []
        dist_map[rid].append(d)

    edge_objs = {}

    for rid, edge in edges_dict.items():

        if rid == 'TERMINATE':
            # list of terminate edges
            edge_objs['TERMINATE'] = []
            for e in edge:
                edge_objs['TERMINATE'].append({
                    "rule_id": "TERMINATE",
                    "type": "TERMINATE",
                    "SOURCE": e["SOURCE"],
                    "TARGET": e["TARGET"],
                    "time_dist": None,
                    "count_dist": None
                })
            continue

        # normal edges
        time_dist = None
        count_dist = None

        for d in dist_map.get(rid, []):
            if d['type'] in ['time_distribution', 'TIME_EXACTLY', 'TIME_RANGE']:
                time_dist = d
            elif d['type'].startswith('COUNT'):
                count_dist = d

        edge_objs[rid] = {
            "rule_id": rid,
            "type": "CAUSE" if rid != 'E0' else "START",
            "SOURCE": edge["SOURCE"],
            "TARGET": edge["TARGET"],
            "time_dist": time_dist,
            "count_dist": count_dist
        }

    return edge_objs

def build_edges_by_source(edge_objs):
    edges_by_source = {}

    for rid, edge in edge_objs.items():

        if rid == 'TERMINATE':
            for e in edge:
                for src in e['SOURCE']:
                    edges_by_source.setdefault(src, []).append(e)
            continue

        for src in edge['SOURCE']:
            edges_by_source.setdefault(src, []).append(edge)

    return edges_by_source

def sample_time(dist_obj):
    if not dist_obj:
        return 0

    if dist_obj['type'] == 'time_distribution':
        val = sample_from_distribution(dist_obj['distribution'])
        return int(val * dist_obj['ratio'])

    elif dist_obj['type'] == 'TIME_EXACTLY':
        return int(dist_obj['value'])

    elif dist_obj['type'] == 'TIME_RANGE':
        return random.randrange(int(dist_obj['start']), int(dist_obj['end']))

    return 0


def sample_count(dist_obj):
    if not dist_obj:
        return 1

    if dist_obj['type'] == 'COUNT_EXACTLY':
        return dist_obj['value']

    elif dist_obj['type'] == 'COUNT_RANGE':
        return random.randrange(dist_obj['start'], dist_obj['end'])

    return 1

def new_null(state):
    val = f"NULL{state['null_counter']}"
    state["null_counter"] += 1
    return val

def build_edges_by_source(edge_objs):
    edges_by_source = {}

    for rid, edge in edge_objs.items():

        if rid == 'TERMINATE':
            for e in edge:
                for src in e['SOURCE']:
                    edges_by_source.setdefault(src, []).append(e)
            continue

        for src in edge['SOURCE']:
            edges_by_source.setdefault(src, []).append(edge)

    return edges_by_source

def sample_time(dist_obj):
    if not dist_obj:
        return 0

    if dist_obj['type'] == 'time_distribution':
        val = sample_from_distribution(dist_obj['distribution'])
        return int(val * dist_obj['ratio'])

    elif dist_obj['type'] == 'TIME_EXACTLY':
        return int(dist_obj['value'])

    elif dist_obj['type'] == 'TIME_RANGE':
        return random.randrange(int(dist_obj['start']), int(dist_obj['end']))

    return 0


def sample_count(dist_obj):
    if not dist_obj:
        return 1

    if dist_obj['type'] == 'COUNT_EXACTLY':
        return dist_obj['value']

    elif dist_obj['type'] == 'COUNT_RANGE':
        return random.randrange(dist_obj['start'], dist_obj['end'])

    return 1

def new_null(state):
    val = f"NULL{state['null_counter']}"
    state["null_counter"] += 1
    return val

def build_attributes(event_type, state, parent_events, event_refs):

    attrs = {}
    schema_attrs = state["events_schema"][event_type]

    for attr in schema_attrs:

        # -------- EVENT REFERENCE --------
        found = False

        for src_event, mapping in event_refs.get(event_type, {}).items():
            if src_event == "AUTO_INCREMENT":
                continue

            if attr in mapping:

                # 🔥 USE CANONICAL PARENT INSTEAD OF DIRECT PARENT
                if src_event in state["canonical_parents"]:
                    src_evt = state["canonical_parents"][src_event]

                    attrs[attr] = src_evt["attrs"][mapping[attr]]
                    found = True
                    break

        if found:
            continue

        # -------- AUTO_INCREMENT --------
        if "AUTO_INCREMENT" in event_refs.get(event_type, {}) and \
           attr in event_refs[event_type]["AUTO_INCREMENT"]:

            if attr not in state["instance_values"]:
                val = state["auto_counters"].get(attr, 0)
                state["auto_counters"][attr] = val + 1
                state["instance_values"][attr] = val

            attrs[attr] = state["instance_values"][attr]
            continue

        # -------- DEFAULT NULL --------
        attrs[attr] = f"NULL{state['null_counter']}"
        state["null_counter"] += 1

    return attrs

def generate_instance(edges_by_source, events, event_refs, start_time, auto_counters):

    state = {
        "event_counts": {},
        "events": [],
        "event_instances": {},
        "active_edges": set(),
        "terminated": False,
        "null_counter": 0,
        "events_schema": events,
        "auto_counters": auto_counters,
        "instance_values": {},
        "canonical_parents": {}
    }

    # 🔥 ADD START EVENT
    start_event = {
        "type": "START",
        "time": start_time - 1, 
        "attrs": {},
        "source_rule_id": "START"
    }
    state["events"].append(start_event)

    for edge in edges_by_source.get("START", []):
        state["active_edges"].add(edge["rule_id"])

    while state["active_edges"] and not state["terminated"]:

        progress = False

        for rid in list(state["active_edges"]):

            edge = None
            for e_list in edges_by_source.values():
                for e in e_list:
                    if e.get("rule_id") == rid:
                        edge = e
                        break
                if edge:
                    break

            if not edge:
                continue

            if edge["SOURCE"] == ["START"]:
                triggerable = True
            else:
                triggerable = all(
                    state["event_counts"].get(src, 0) > 0
                    for src in edge["SOURCE"]
                )

            if not triggerable:
                continue

            parent_times = []
            parent_events = {}

            for src in edge["SOURCE"]:
                if src == "START":
                    parent_times.append(start_time)
                else:
                    evt = state["event_instances"][src][-1]
                    parent_times.append(evt["time"])
                    parent_events[src] = evt

            parent_time = max(parent_times)

            count = sample_count(edge["count_dist"])

            for _ in range(count):
                for tgt in edge["TARGET"]:

                    delay = sample_time(edge["time_dist"])
                    event_time = parent_time + delay

                    attrs = build_attributes(
                        tgt,
                        state,
                        parent_events,
                        event_refs
                    )

                    evt = {
                        "type": tgt,
                        "time": event_time,
                        "attrs": attrs,
                        "source_rule_id": edge["rule_id"]
                    }

                    state["events"].append(evt)
                    state["event_counts"][tgt] = state["event_counts"].get(tgt, 0) + 1
                    state["event_instances"].setdefault(tgt, []).append(evt)

                    # 🔥 CANONICAL PARENT LOGIC
                    # If this event type has no canonical parent yet → set it
                    if tgt not in state["canonical_parents"]:
                        state["canonical_parents"][tgt] = evt

                    # Otherwise KEEP existing canonical (important for loops!)

                    for next_edge in edges_by_source.get(tgt, []):
                        state["active_edges"].add(next_edge.get("rule_id", "TERMINATE"))

            state["active_edges"].remove(rid)
            progress = True

        if not progress:
            break

    # 🔥 ADD END EVENT
    if state["events"]:
        last_time = max(evt["time"] for evt in state["events"])
    else:
        last_time = start_time

    end_event = {
        "type": "END",
        "time": last_time + 1,
        "attrs": {},
        "source_rule_id": "TERMINATE"
    }

    state["events"].append(end_event)

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

    # find TIMECOUNT distribution
    start_dist = None
    for d in distributions:
        if d["type"] == "timecount_distribution":
            start_dist = d
            break

    if not start_dist:
        raise ValueError("Missing TIMECOUNT distribution")

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
                event_refs,
                base_time,
                auto_counters   # 🔥 pass shared counters
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
    log_output
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

    # find TIMECOUNT distribution
    start_dist = None
    for d in distributions:
        if d["type"] == "timecount_distribution":
            start_dist = d
            break

    if not start_dist:
        raise ValueError("Missing TIMECOUNT distribution")

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
                edges_by_source,
                events,
                event_refs,
                base_time,
                auto_counters
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

def run_quick_test(edges_by_source, events, event_refs, distributions, start, auto_counters, num_instances):
    import random
    # find TIMECOUNT distribution
    start_dist = None
    for d in distributions:
        if d["type"] == "timecount_distribution":
            start_dist = d
            break

    if not start_dist:
        raise ValueError("Missing TIMECOUNT distribution")

    print(f"\n=== QUICK TEST: {num_instances} INSTANCE(S) ===\n")

    for inst_id in range(num_instances):

        # pick a bucket (you can randomize or keep first)
        bucket = random.choice(start_dist["distribution"])

        start_h = int(bucket["distribution_range"]["start"])
        end_h   = int(bucket["distribution_range"]["end"])

        start_t = int(start + start_h * start_dist["ratio"])
        end_t   = int(start + end_h   * start_dist["ratio"])

        base_time = random.randrange(start_t, end_t)

        instance = generate_instance(
            edges_by_source,
            events,
            event_refs,
            base_time,
            auto_counters
        )

        # remove START/END
        instance = [e for e in instance if e["type"] not in ("START", "END")]

        instance.sort(key=lambda x: x["time"])

        print(f"\n--- Instance {inst_id} ---")

        for i, evt in enumerate(instance, 1):
            print(f"{i:02d} | t={evt['time']:4d} | {evt['type']} | rule={evt['source_rule_id']}")
            for k, v in evt["attrs"].items():
                print(f"     {k}: {v}")



import argparse

def main():
    parser = argparse.ArgumentParser(description="Event stream generator")

    parser.add_argument(
        "--quick_test",
        nargs="?",
        const=1,
        type=int,
        help="Generate and print N instances (default = 1 if flag is used without value)"
    )

    args = parser.parse_args()

    # --- Load data ---
    with open('output_xml/bike_rental_info.xml', 'r', encoding='utf-8') as file:
        data_dict = xmltodict.parse(file.read())

    events = extract_events(data_dict)
    edges_dict = extract_event_edges(data_dict)
    refs = extract_event_refs(data_dict)
    dists = extract_distributions(data_dict)

    edge_objs = build_edges(edges_dict, dists)
    edges_by_source = build_edges_by_source(edge_objs)

    base = data_dict['root']['global_configurations']['base_time_granularity']

    start = time_conversion(
        data_dict['root']['global_configurations']['time_range']['start_time'],
        base
    )

    end = time_conversion(
        data_dict['root']['global_configurations']['time_range']['end_time'],
        base
    )

    # 🔥 GLOBAL AUTO_INCREMENT counters
    auto_counters = {}
    for evt in refs:
        if "AUTO_INCREMENT" in refs[evt]:
            for attr in refs[evt]["AUTO_INCREMENT"]:
                auto_counters[attr] = 0

    if args.quick_test is not None:
        run_quick_test(
            edges_by_source,
            events,
            refs,
            dists,
            start,
            auto_counters,
            args.quick_test
        )
    else:
        generate_event_stream_outputs(
            edges_by_source,
            events,
            refs,
            dists,
            start,
            end,
            "./output_xml/bike_rental_stream.xml",
            "./bike_rental_log.txt"
        )


if __name__ == "__main__":
    main()

''' 
idx = 0
event_stream = {}

while curr <= end:
	num = num_dist[curr % granularity]
	active_edges = deque(["E0"])
	curr_event_stream = {}
	for _ in range(num):
		curr_events = [{k: []} for k in events.keys()]
		t = random.randint(0, granularity)
		curr_edge = active_edges.popleft()
		while any(e not in finished for e in event_edges[curr_edge]["SOURCE"]):
			active_edges.append(curr_edge)
			curr_edge = active_edges.popleft()
		for target in event_edges[curr_edge]["TARGET"]:
			target_event = events[target]
			for k in event_refs[target]:
				if k.key() == "AUTO_INCREMENT":
					for att, val in k["AUTO_INCREMENT"]:
						target_event[att] = val
						k["AUTO_INCREMENT"][att] = val + 1
				else:
					ref_event = k.key()	
	curr += granularity
'''
