def choose_or_generate_user(context, probability_new=0.2):
	import random

	from faker import Faker

	from data_generator_engine.db_oracle import get_connection

	conn = get_connection()
	cursor = conn.cursor()
	cursor.execute("SELECT user_id FROM Users WHERE user_id IS NOT NULL")
	existing_ids = [row[0] for row in cursor.fetchall()]

	if existing_ids and random.random() >= probability_new:
		return random.choice(existing_ids)

	cursor.execute("SELECT MAX(user_id) FROM Users")
	max_user_id = cursor.fetchone()[0]
	if max_user_id is None:
		max_user_id = 1000

	cursor.execute("SELECT MAX(id) FROM Users")
	max_id = cursor.fetchone()[0]
	if max_id is None:
		max_id = 0

	new_user_id = max_user_id + 1
	new_id = max_id + 1
	faker = Faker()
	first_name = faker.first_name()
	last_name = faker.last_name()
	email = f"{first_name.lower()}.{last_name.lower()}@example.com"
	phone = faker.numerify("212-###-####")
	credit_card_num = faker.credit_card_number()
	is_member = 1 if faker.boolean() else 0
	cursor.execute(
		"""
		INSERT INTO Users (
			id,
			user_id,
			first_name,
			last_name,
			email,
			phone,
			credit_card_num,
			is_member,
			created_at,
			updated_at
		) VALUES (
			:1,
			:2,
			:3,
			:4,
			:5,
			:6,
			:7,
			:8,
			CURRENT_TIMESTAMP,
			CURRENT_TIMESTAMP
		)
		""",
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
	)
	conn.commit()
	return new_user_id


def choose_station(context):
	import random

	from data_generator_engine.db_oracle import get_connection

	conn = get_connection()
	cursor = conn.cursor()
	cursor.execute(
		"""
		SELECT station_id
		FROM Stations
		WHERE bikes_available > 0
		"""
	)
	station_ids = [row[0] for row in cursor.fetchall()]
	if not station_ids:
		raise ValueError("No stations with available bikes")
	return random.choice(station_ids)


def choose_available_bike(context):
	import random

	from data_generator_engine.db_oracle import get_connection

	station_id = context["attributes"].get("station_id")
	if station_id is None:
		raise KeyError("station_id is required before choosing a bike")

	conn = get_connection()
	cursor = conn.cursor()
	cursor.execute(
		"""
		SELECT bike_id
		FROM Bikes
		WHERE station_id = :1
		  AND status IN ('available')
		  AND bike_id IS NOT NULL
		""",
		(station_id,),
	)
	bike_ids = [row[0] for row in cursor.fetchall()]
	if not bike_ids:
		raise ValueError(f"No available bikes at station_id={station_id}")
	
	selected_bike_id = random.choice(bike_ids)
	
	# Update bike status to 'rented'
	cursor.execute(
		"""
		UPDATE Bikes
		SET status = 'rented'
		WHERE bike_id = :1
		""",
		(selected_bike_id,),
	)
	
	# Decrement bikes_available and increment capacity_available at station
	cursor.execute(
		"""
		UPDATE Stations
		SET bikes_available = bikes_available - 1,
		    capacity_available = capacity_available + 1
		WHERE station_id = :1
		""",
		(station_id,),
	)
	
	conn.commit()
	return selected_bike_id


def generate_report_location(context, max_miles=40, nyc_bounds=None, attempts=10):
	import math
	import random

	if nyc_bounds is None:
		nyc_bounds = (-74.25909, -73.70018, 40.477399, 40.917577)

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

	lon_min, lon_max, lat_min, lat_max = nyc_bounds
	for _ in range(int(attempts)):
		distance = random.random() * max_distance
		bearing = random.random() * 2 * math.pi
		lon_new, lat_new = destination_point(lon0, lat0, distance, bearing)
		if lon_min <= lon_new <= lon_max and lat_min <= lat_new <= lat_max:
			return (round(lon_new, 6), round(lat_new, 6))

	return (round(lon0, 6), round(lat0, 6))


def choose_return_station(context, max_miles=40, nyc_bounds=None):
	import math
	import random

	from data_generator_engine.db_oracle import get_connection

	if nyc_bounds is None:
		nyc_bounds = (-74.25909, -73.70018, 40.477399, 40.917577)

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

	if last_location is None:
		last_location = attributes.get("location_data")

	last_coords = parse_location(last_location)
	if last_coords is None:
		raise KeyError("last ReportLocation location_data is required before ReturnBike station selection")

	lon0, lat0 = last_coords

	conn = get_connection()
	cursor = conn.cursor()
	try:
		cursor.execute(
			"""
			SELECT station_id, longitude, latitude
			FROM Stations
			WHERE capacity_available > 0
			"""
		)
		rows = cursor.fetchall()

		if not rows:
			raise ValueError("No stations with capacity_available > 0")

		max_distance = float(max_miles)
		if max_distance <= 0:
			raise ValueError("max_miles must be positive")

		lon_min, lon_max, lat_min, lat_max = nyc_bounds
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
			raise ValueError("No stations within range of last ReportLocation")

		selected_station_id = random.choice(candidates)
		cursor.execute(
			"""
			UPDATE Bikes
			SET station_id = :1,
			    status = 'available'
			WHERE bike_id = :2
			""",
			(selected_station_id, bike_id),
		)
		cursor.execute(
			"""
			UPDATE Stations
			SET bikes_available = bikes_available + 1,
			    capacity_available = capacity_available - 1
			WHERE station_id = :1
			""",
			(selected_station_id,),
		)
		conn.commit()
		return selected_station_id
	finally:
		cursor.close()
		conn.close()
