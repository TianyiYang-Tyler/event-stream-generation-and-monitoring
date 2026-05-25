def choose_or_generate_user(context, probability_new=0.2, seeded_max_user_id=None):
	import random

	from faker import Faker

	cache = context.get("resource_cache")
	if cache is None:
		raise RuntimeError("resource_cache is required in context")

	# "Existing" means a user that was seeded in the database. New users created
	# during the run must NOT count as existing, or the seeded/new ratio drifts
	# (the "existing" pool would grow with every new user we mint).
	#
	# The seeded pool is captured ONCE, on the first call, by snapshotting the
	# user_ids currently in the cache. At that point no new users have been
	# minted yet (this function is what mints them), so the snapshot is exactly
	# the seeded set. This is robust: it does not depend on a hardcoded
	# threshold that can silently drift when USERS_COUNT changes.
	#
	# If seeded_max_user_id is explicitly provided, it is still honored as an
	# upper bound (useful if you want to cap the seeded set deliberately).
	seeded_ids = getattr(cache, "_seeded_user_ids_cache", None)
	if seeded_ids is None:
		seeded_ids = [
			uid for uid in cache.users.keys()
			if uid is not None
			and (seeded_max_user_id is None or uid <= seeded_max_user_id)
		]
		cache._seeded_user_ids_cache = seeded_ids

	# Preserve original RNG call order: draw once to decide existing vs new.
	if seeded_ids and random.random() >= probability_new:
		return random.choice(seeded_ids)

	new_user_id, new_id = cache.next_user_ids()
	faker = Faker()
	first_name = faker.first_name()
	last_name = faker.last_name()
	email = f"{first_name.lower()}.{last_name.lower()}@example.com"
	phone = faker.numerify("###-###-####")
	credit_card_num = faker.credit_card_number()
	is_member = 1 if faker.boolean() else 0

	cache.add_user(
		(
			new_id,
			new_user_id,
			first_name,
			last_name,
			email,
			phone,
			credit_card_num,
			is_member,
		),
		is_member=is_member,
		credit_card_num=credit_card_num,
	)
	return new_user_id


def choose_station(context):
	import random

	cache = context.get("resource_cache")
	if cache is None:
		raise RuntimeError("resource_cache is required in context")

	station_ids = [
		sid
		for sid, station in cache.stations.items()
		if (station.get("bikes_available") or 0) > 0
	]
	if not station_ids:
		raise ValueError("No stations with available bikes")
	return random.choice(station_ids)


def choose_available_bike(context):
	import random

	cache = context.get("resource_cache")
	if cache is None:
		raise RuntimeError("resource_cache is required in context")

	station_id = context["attributes"].get("station_id")
	if station_id is None:
		raise KeyError("station_id is required before choosing a bike")
	try:
		station_id = int(station_id)
	except (TypeError, ValueError):
		raise KeyError("station_id must be numeric before choosing a bike")

	bike_ids = [
		bid
		for bid, bike in cache.bikes.items()
		if bike.get("station_id") == station_id and bike.get("status") == "available"
	]
	if not bike_ids:
		raise ValueError(f"No available bikes at station_id={station_id}")

	selected_bike_id = random.choice(bike_ids)

	# Mutate bike + station availability in memory; flushed in one batch later.
	cache.bikes[selected_bike_id]["status"] = "rented"
	cache.mark_bike_dirty(selected_bike_id)

	station = cache.stations[station_id]
	station["bikes_available"] = (station.get("bikes_available") or 0) - 1
	station["capacity_available"] = (station.get("capacity_available") or 0) + 1
	cache.mark_station_dirty(station_id)

	return selected_bike_id


def generate_report_location(context, max_miles=10, sf_bounds=None, attempts=10):
	import math
	import random

	if sf_bounds is None:
		sf_bounds = (-122.55, -121.80, 37.25, 37.95)

	def parse_location(value):
		if value is None:
			return None
		if isinstance(value, (list, tuple)) and len(value) >= 2:
			return float(value[0]), float(value[1])
		text = str(value).strip()
		if text.startswith("(") and text.endswith(")"):
			text = text[1:-1]
		parts = [part.strip() for part in text.split(",")]
		if len(parts) >= 2:
			return float(parts[0]), float(parts[1])
		return None

	attributes = context.get("attributes", {})
	session_id = attributes.get("session_id")
	previous_location = None

	runtime_state = context.get("runtime_state")
	if runtime_state is not None and session_id is not None:
		match_key = runtime_state.build_key(attributes, ["session_id"])
		try:
			previous_location = runtime_state.lookup(
				"ReportLocation", ["session_id"], match_key, "location_data"
			)
		except KeyError:
			previous_location = None
		if previous_location is None:
			try:
				previous_location = runtime_state.lookup(
					"RentBike", ["session_id"], match_key, "location_data"
				)
			except KeyError:
				previous_location = None

	if previous_location is None:
		previous_location = attributes.get("location_data")

	previous_coords = parse_location(previous_location)
	if previous_coords is None:
		raise KeyError("previous location_data is required before generating a report location")

	lon0, lat0 = previous_coords
	max_distance = float(max_miles)
	if max_distance <= 0:
		return (round(lon0, 6), round(lat0, 6))

	radius_miles = 3958.8

	def destination_point(lon_deg, lat_deg, distance_miles, bearing_rad):
		lat1 = math.radians(lat_deg)
		lon1 = math.radians(lon_deg)
		delta = distance_miles / radius_miles
		lat2 = math.asin(
			math.sin(lat1) * math.cos(delta)
			+ math.cos(lat1) * math.sin(delta) * math.cos(bearing_rad)
		)
		lon2 = lon1 + math.atan2(
			math.sin(bearing_rad) * math.sin(delta) * math.cos(lat1),
			math.cos(delta) - math.sin(lat1) * math.sin(lat2),
		)
		return math.degrees(lon2), math.degrees(lat2)

	lon_min, lon_max, lat_min, lat_max = sf_bounds
	for _ in range(int(attempts)):
		distance = random.random() * max_distance
		bearing = random.random() * 2 * math.pi
		lon_new, lat_new = destination_point(lon0, lat0, distance, bearing)
		if lon_min <= lon_new <= lon_max and lat_min <= lat_new <= lat_max:
			return (round(lon_new, 6), round(lat_new, 6))

	return (round(lon0, 6), round(lat0, 6))


def choose_return_station(context, max_miles=10, sf_bounds=None):
	import math
	import random

	cache = context.get("resource_cache")
	if cache is None:
		raise RuntimeError("resource_cache is required in context")

	if sf_bounds is None:
		sf_bounds = (-122.55, -121.80, 37.25, 37.95)

	def parse_location(value):
		if value is None:
			return None
		if isinstance(value, (list, tuple)) and len(value) >= 2:
			return float(value[0]), float(value[1])
		text = str(value).strip()
		if text.startswith("(") and text.endswith(")"):
			text = text[1:-1]
		parts = [part.strip() for part in text.split(",")]
		if len(parts) >= 2:
			return float(parts[0]), float(parts[1])
		return None

	def haversine_miles(lon1, lat1, lon2, lat2):
		radius_miles = 3958.8
		lat1_rad = math.radians(lat1)
		lat2_rad = math.radians(lat2)
		dlat = math.radians(lat2 - lat1)
		dlon = math.radians(lon2 - lon1)
		a = (
			math.sin(dlat / 2) ** 2
			+ math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
		)
		c = 2 * math.asin(math.sqrt(a))
		return radius_miles * c

	attributes = context.get("attributes", {})
	session_id = attributes.get("session_id")
	runtime_state = context.get("runtime_state")
	bike_id = attributes.get("bike_id")
	if bike_id is None or str(bike_id).startswith("NULL"):
		raise KeyError("bike_id is required before choosing a return station")
	try:
		bike_id = int(bike_id)
	except (TypeError, ValueError):
		raise KeyError("bike_id must be a numeric value before choosing a return station")

	last_location = None
	if runtime_state is not None and session_id is not None:
		match_key = runtime_state.build_key(attributes, ["session_id"])
		try:
			last_location = runtime_state.lookup(
				"ReportLocation", ["session_id"], match_key, "location_data"
			)
		except KeyError:
			last_location = None
		# A session may legitimately have no ReportLocation (rent then return
		# with no location reports). In that case the bike is still at its
		# pickup station, so fall back to the RentBike's recorded location.
		if last_location is None:
			try:
				last_location = runtime_state.lookup(
					"RentBike", ["session_id"], match_key, "location_data"
				)
			except KeyError:
				last_location = None

	if last_location is None:
		last_location = attributes.get("location_data")

	last_coords = parse_location(last_location)
	if last_coords is None:
		raise KeyError("location_data is required before ReturnBike station selection (no ReportLocation or RentBike location found for this session)")

	lon0, lat0 = last_coords

	rows = [
		(sid, station.get("longitude"), station.get("latitude"))
		for sid, station in cache.stations.items()
		if (station.get("capacity_available") or 0) > 0
	]
	if not rows:
		raise ValueError("No stations with capacity_available > 0")

	max_distance = float(max_miles)
	if max_distance <= 0:
		raise ValueError("max_miles must be positive")

	lon_min, lon_max, lat_min, lat_max = sf_bounds
	candidates = []
	for station_id, lon, lat in rows:
		if lon is None or lat is None:
			continue
		if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
			continue
		distance = haversine_miles(lon0, lat0, float(lon), float(lat))
		if distance <= max_distance:
			candidates.append(station_id)

	if not candidates:
		candidates = [row[0] for row in rows]
		if not candidates:
			raise ValueError("No stations within range of last ReportLocation")

	selected_station_id = random.choice(candidates)

	# Mutate bike + station state in memory; flushed in one batch later.
	if bike_id in cache.bikes:
		cache.bikes[bike_id]["station_id"] = selected_station_id
		cache.bikes[bike_id]["status"] = "available"
		cache.mark_bike_dirty(bike_id)

	station = cache.stations[selected_station_id]
	station["bikes_available"] = (station.get("bikes_available") or 0) + 1
	station["capacity_available"] = (station.get("capacity_available") or 0) - 1
	cache.mark_station_dirty(selected_station_id)

	return selected_station_id
