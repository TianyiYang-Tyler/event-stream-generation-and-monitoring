import random
from collections import deque
import xmltodict
import random

def unit_to_ratio(unit):
	if unit == 'MISCROSECOND':
		return 1
	elif unit == 'SECOND':
		return 1e6
	elif unit == 'MINUTE':
		return 6 * 1e7
	elif unit == 'HOUR':
		return 3.6 * 1e9
	elif unit == 'DAY':
		return 8.64 * 1e10
	else:
		return -1

def time_conversion(org, base_time_granularity):
	if org['unit'] == 'DEFAULT':
		return org['value']
	if (unit_to_ratio(org['unit']) * int(org['value'])) % (unit_to_ratio(base_time_granularity['unit']) * int(base_time_granularity['value'])) != 0:	
		raise ValueError(f"{org} violates base granularity constraint!")
	return (unit_to_ratio(org['unit']) * int(org['value'])) / (unit_to_ratio(base_time_granularity['unit']) * int(base_time_granularity['value']))

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

            if attr_type['type'] == 'event_reference':
                src_event = attr_type['event_name']
                src_attr = attr_type['event_values']

                if src_event not in refs[event_name]:
                    refs[event_name][src_event] = {}

                refs[event_name][src_event][attr_name] = src_attr

            elif attr_type['type'] == 'global_restricted':
                # treat as special AUTO_INCREMENT bucket
                if "AUTO_INCREMENT" not in refs[event_name]:
                    refs[event_name]["AUTO_INCREMENT"] = {}

                refs[event_name]["AUTO_INCREMENT"][attr_name] = 0

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
            "rule_id": dist['rule_id'],
            "type": dist['type'],
            "base": dist['base_time_granularity_value'],
            "distribution": dist['distribution']
        })

    # --- 2. process_schema conditions ---
    for rule in data['root']['process_schema']:
        rule_id = rule['rule_id']

        # time_condition
        tc = rule.get('target_event', {}).get('time_condition') \
             if rule['type'] == 'CAUSE' else None

        if tc:
            if tc['type'] == 'EXACTLY':
                val = time_conversion(tc['time'], base)
                results.append({
                    "rule_id": rule_id,
                    "type": "EXACTLY",
                    "value": val
                })

            elif tc['type'] == 'RANGE':
                start = time_conversion(tc['start_time'], base)
                end = time_conversion(tc['end_time'], base)
                results.append({
                    "rule_id": rule_id,
                    "type": "RANGE",
                    "start": start,
                    "end": end
                })

        # count_condition — same idea
        tc = rule.get('target_event', {}).get('time_condition') \
             if rule['type'] == 'CAUSE' else None

        if tc:
            if tc['type'] == 'EXACTLY':
                val = time_conversion(tc['time'], base)
                results.append({
                    "rule_id": rule_id,
                    "type": "EXACTLY",
                    "value": val
                })

            elif tc['type'] == 'RANGE':
                start = time_conversion(tc['start_time'], base)
                end = time_conversion(tc['end_time'], base)
                results.append({
                    "rule_id": rule_id,
                    "type": "RANGE",
                    "start": start,
                    "end": end
                })

    return results

data_dict = {}
# From a file
with open('output_xml/bike_rental_info.xml', 'r', encoding='utf-8') as file:
    data_dict = xmltodict.parse(file.read())

base_time_granularity = data_dict['root']['global_configurations']['base_time_granularity']
start, end = time_conversion(data_dict['root']['global_configurations']['time_range']['start_time'], base_time_granularity), time_conversion(data_dict['root']['global_configurations']['time_range']['end_time'], base_time_granularity)

#print(data_dict)
print(data_dict)
'''
for curr in range(int(start), int(end)):
	
event_refs = {"RentBike": {"AUTO_INCREMENT": {"session_id" = 0}}, "ReturnBike": {"RentBike": {"user_id": "user_id", "bike_id": "bike_id", "session_id": "session_id", "credit_card_num": "credit_card_num", "is_member": "is_member"}}, "ReportLocation": {"RentBike": {"user_id": "user_id", "bike_id": "bike_id", "session_id": "session_id"}}}
event_edges = {"E0": {"SOURCE": ["START"], "TARGET": ["RentBike"]}, "E1": {"SOURCE": ["RentBike"], "TARGET": ["ReturnBike"]}, "E2": {"SOURCE": ["RentBike"], "TARGET": ["ReportLocation"]}, "E3": {"SOURCE": ["ReportLocation"], "TARGET": ["ReportLocation"]}}
events = {}
events["RentBike"] = ["user_id", "bike_id", "session_id", "station_id", "station_name", "location_data", "credit_card_num", "is_member"]
events["ReturnBike"] = ["user_id", "bike_id", "session_id", "station_id", "station_name", "location_data", "credit_card_num", "is_member"]
events["ReportLocation"] = ["user_id", "bike_id", "session_id", "station_id", "station_name", "location_data"]

time_dist = {}
count_dist = {}
num_dist = RangeDict({Range(0, 1000): 5, Range(1000, 2200): 30, Range(2200, 3600): 15})
granularity = 3600
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
