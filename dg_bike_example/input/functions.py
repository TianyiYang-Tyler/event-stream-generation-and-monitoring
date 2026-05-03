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
