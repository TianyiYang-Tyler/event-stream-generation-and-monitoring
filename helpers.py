import random
from collections import deque
import xmltodict
import xml.etree.ElementTree as ET
import math

def extract_termination_rules(data):

    results = []

    for rule in data['root']['process_schema']:

        if rule['type'] != 'TERMINATE':
            continue

        terminator = rule['source_events']
        targets = rule['target_event']

        # TERMINATE ReturnBike
        # => terminate ALL
        if targets == "ALL":

            results.append({
                "terminator": terminator,
                "targets": "ALL"
            })

        else:

            if not isinstance(targets, list):
                targets = [targets]

            results.append({
                "terminator": terminator,
                "targets": targets
            })

    return results

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

def extract_termination_rules(data):

    results = []

    for rule in data['root']['process_schema']:

        if rule['type'] != 'TERMINATE':
            continue

        terminator = rule['source_events']

        targets = rule['target_event']

        if not isinstance(targets, list):
            targets = [targets]

        for tgt in targets:

            results.append({
                "terminator": terminator,
                "source": tgt
            })

    return results

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

    value = float(org['value'])

    if org['unit'] == 'DEFAULT':
        return int(value)

    if (unit_to_ratio(org['unit']) * value) % (
        unit_to_ratio(base_time_granularity['unit']) *
        float(base_time_granularity['value'])
    ) != 0:
        raise ValueError(f"{org} violates base granularity constraint!")

    return int(
        (unit_to_ratio(org['unit']) * value) /
        (
            unit_to_ratio(base_time_granularity['unit']) *
            float(base_time_granularity['value'])
        )
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

    # =========================================================
    # 1. Explicit event_distributions section
    # =========================================================
    for dist in data['root'].get('event_distributions', []):

        parsed = {
            "rule_id": dist['rule_id'],
            "type": dist['type'],
            "distribution": dist['distribution']
        }

        # only time-based distributions need ratio
        if dist['type'] in ('start_distribution', 'time_distribution'):
            parsed["ratio"] = time_conversion(
                dist['base_time_granularity_value'],
                base
            )

        results.append(parsed)

    # =========================================================
    # 2. Inline process_schema conditions
    # =========================================================
    for rule in data['root']['process_schema']:

        # skip rules without rule_id (e.g. TERMINATE)
        rule_id = rule.get('rule_id')
        if not rule_id:
            continue

        if rule['type'] != 'CAUSE':
            continue

        target = rule.get('target_event', {})

        # -----------------------------------------------------
        # TIME CONDITION
        # -----------------------------------------------------
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

        # -----------------------------------------------------
        # COUNT CONDITION
        # -----------------------------------------------------
        cc = target.get('count_condition')

        if cc:

            if cc['type'] == 'EXACTLY':

                results.append({
                    "rule_id": rule_id,
                    "type": "COUNT_EXACTLY",
                    "value": int(float(cc['count']))
                })

            elif cc['type'] == 'RANGE':

                results.append({
                    "rule_id": rule_id,
                    "type": "COUNT_RANGE",
                    "start": int(float(cc['start_count'])),
                    "end": int(float(cc['end_count']))
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
    termination_rules = []

    for rid, edge in edge_objs.items():

        # -----------------------------------------
        # TERMINATION RULES
        # -----------------------------------------
        if rid == 'TERMINATE':

            for e in edge:

                termination_rules.append({
                    "source": e["SOURCE"],
                    "terminator": e["TARGET"]
                })

            continue

        # -----------------------------------------
        # NORMAL GENERATIVE EDGES
        # -----------------------------------------
        for src in edge['SOURCE']:
            edges_by_source.setdefault(src, []).append(edge)

    return edges_by_source, termination_rules

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

def build_attributes(event_type, state, parent_events, event_refs, raw_schema):
    """
    raw_schema: the full event_type_definitions list from the parsed dict,
                needed to read attribute_type details (not just attr names).
    """
    attrs = {}

    # Find this event's attribute definitions
    event_def = next(
        e for e in raw_schema
        if e["event_name"] == event_type
    )

    for attr_def in event_def["attributes"]:
        attr_name = attr_def["attribute_name"]
        attr_type = attr_def["attribute_type"]

        # Normalize string shorthand
        if isinstance(attr_type, str):
            attr_type = {"type": attr_type}

        t = attr_type.get("type")

        # --------------------------------------------------
        # AUTO_INCREMENT
        # --------------------------------------------------
        if t == "AUTO_INCREMENT":
            val = state["auto_counters"].get(attr_name, 0)
            state["auto_counters"][attr_name] = val + 1
            attrs[attr_name] = val

        # --------------------------------------------------
        # EVENT REFERENCE — copy value from prior event
        # --------------------------------------------------
        elif t == "event_reference":
            src_event_name = attr_type["event_name"]
            src_cols = attr_type["event_values"]
            # xmltodict gives a string when there's one element, list when multiple
            if isinstance(src_cols, str):
                src_cols = [src_cols]

            src_evt = state["canonical_parents"].get(src_event_name)

            if src_evt and len(src_cols) == 1:
                attrs[attr_name] = src_evt["attrs"].get(src_cols[0], _new_null(state))
            elif src_evt and len(src_cols) > 1:
                attrs[attr_name] = [
                    src_evt["attrs"].get(c, _new_null(state))
                    for c in src_cols
                ]
            else:
                attrs[attr_name] = _new_null(state)

        # --------------------------------------------------
        # TABLE REFERENCE — unique NULL per attribute
        # --------------------------------------------------
        elif t == "table_reference":
            attrs[attr_name] = _new_null(state)

        # --------------------------------------------------
        # GLOBAL RESTRICTED — fresh NULL (positional, not reused)
        # --------------------------------------------------
        elif t == "global_restricted":
            attrs[attr_name] = _new_null(state)

        # --------------------------------------------------
        # FALLBACK
        # --------------------------------------------------
        else:
            attrs[attr_name] = _new_null(state)

    return attrs


def _new_null(state):
    val = f"NULL{state['null_counter']}"
    state["null_counter"] += 1
    return val


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
