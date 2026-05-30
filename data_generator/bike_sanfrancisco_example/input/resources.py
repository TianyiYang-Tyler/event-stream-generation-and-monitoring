from __future__ import annotations

import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from faker import Faker

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from data_generator_engine.db_oracle import get_connection

SEED = 42
USERS_COUNT = 75000
STATIONS_COUNT = 700
BIKES_COUNT = 10000
SCHEMA_NAME = "appuser"
DROP_EXISTING = True
STATION_INFO_URL = "https://gbfs.baywheels.com/gbfs/en/station_information.json"
SF_STATION_NAMES = [
	"Market St & 5th St",
	"Market St & 7th St",
	"Market St & 10th St",
	"Market St & 2nd St",
	"Market St & 8th St",
	"Embarcadero & Folsom St",
	"Embarcadero & Broadway",
	"Embarcadero & Bryant St",
	"Embarcadero & Sansome St",
	"Townsend St & 4th St",
	"King St & 4th St",
	"2nd St & King St",
	"3rd St & Townsend St",
	"Mission Bay Blvd & 4th St",
	"Howard St & 2nd St",
	"Howard St & Beale St",
	"Folsom St & 2nd St",
	"Folsom St & 4th St",
	"Spear St & Market St",
	"Montgomery St & Market St",
	"Powell St & Market St",
	"Civic Center Plaza",
	"Van Ness Ave & Market St",
	"Valencia St & 16th St",
	"Valencia St & 18th St",
	"24th St & Mission St",
	"17th St & Castro St",
	"Divisadero St & Grove St",
	"Fillmore St & Geary Blvd",
	"Haight St & Stanyan St",
	"Ocean Ave & Phelan Ave",
	"Lombard St & Fillmore St",
	"Columbus Ave & Washington St",
	"Pier 39",
	"Fort Mason Center",
]
# Bay Wheels stations and generated report locations span a broad Bay Area footprint.
SF_BOUNDS = (-122.55, -121.80, 37.25, 37.95)


def qualify(table: str) -> str:
	return f"{SCHEMA_NAME}.{table}" if SCHEMA_NAME else table


def random_sf_coordinates() -> tuple[float, float]:
	lon_min, lon_max, lat_min, lat_max = SF_BOUNDS
	return (
		random.uniform(lon_min, lon_max),
		random.uniform(lat_min, lat_max),
	)


def load_station_catalog() -> list[tuple[str, float, float]]:
	try:
		with urlopen(STATION_INFO_URL, timeout=10) as response:
			payload = json.load(response)
		stations = payload.get("data", {}).get("stations", [])
		catalog = []
		for station in stations:
			name = station.get("name")
			lon = station.get("lon")
			lat = station.get("lat")
			if name is None or lon is None or lat is None:
				continue
			catalog.append((str(name), float(lon), float(lat)))
		if catalog:
			return catalog
	except (URLError, TimeoutError, ValueError, json.JSONDecodeError):
		pass

	return [(name, *random_sf_coordinates()) for name in SF_STATION_NAMES]


def create_tables(cursor) -> None:
	statements = [
		f"""
		CREATE TABLE {qualify('Stations')} (
			station_id NUMBER(19) PRIMARY KEY,
			id NUMBER(19) UNIQUE,
			name VARCHAR2(255) NOT NULL,
			longitude NUMBER(9,6) NOT NULL,
			latitude NUMBER(9,6) NOT NULL,
			address VARCHAR2(255),
			city VARCHAR2(120),
			state VARCHAR2(120),
			postal_code VARCHAR2(20),
			capacity NUMBER(10),
			capacity_available NUMBER(10),
			bikes_available NUMBER(10),
			created_at TIMESTAMP,
			updated_at TIMESTAMP
		)
		""",
		f"""
		CREATE TABLE {qualify('Users')} (
			id NUMBER(19) PRIMARY KEY,
			user_id NUMBER(19) UNIQUE,
			first_name VARCHAR2(120),
			last_name VARCHAR2(120),
			email VARCHAR2(255),
			phone VARCHAR2(40),
			credit_card_num VARCHAR2(32),
			is_member NUMBER(1),
			created_at TIMESTAMP,
			updated_at TIMESTAMP
		)
		""",
		f"""
		CREATE TABLE {qualify('Bikes')} (
			id NUMBER(19) PRIMARY KEY,
			bike_id NUMBER(19) UNIQUE,
			brand VARCHAR2(120),
			model VARCHAR2(120),
			bike_type VARCHAR2(80),
			status VARCHAR2(40),
			station_id NUMBER(19) NOT NULL,
			purchased_at DATE,
			created_at TIMESTAMP,
			updated_at TIMESTAMP,
			CONSTRAINT fk_bikes_station FOREIGN KEY (station_id) REFERENCES {qualify('Stations')}(station_id)
		)
		""",
	]
	for statement in statements:
		try:
			cursor.execute(statement)
		except Exception as exc:
			if "ORA-00955" not in str(exc):
				raise


def drop_tables(cursor) -> None:
	statements = [
		f"DROP TABLE {qualify('Bikes')} CASCADE CONSTRAINTS",
		f"DROP TABLE {qualify('Stations')} CASCADE CONSTRAINTS",
		f"DROP TABLE {qualify('Users')} CASCADE CONSTRAINTS",
	]
	for statement in statements:
		try:
			cursor.execute(statement)
		except Exception as exc:
			if "ORA-00942" not in str(exc):
				raise


def main() -> None:
	fake = Faker()
	Faker.seed(SEED)
	random.seed(SEED)

	conn = get_connection()
	cursor = conn.cursor()

	created_base = datetime(2026, 4, 2, 9, 0, 0)
	updated_base = datetime(2026, 4, 20, 10, 0, 0)
	station_catalog = load_station_catalog()

	try:
		if DROP_EXISTING:
			drop_tables(cursor)
		create_tables(cursor)

		# Insert users in batches to avoid huge in-memory lists and to show progress.
		import time

		BATCH_SIZE = 5000

		user_insert_sql = f"""
			INSERT INTO {qualify('Users')} (
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
				:9,
				:10
			)
			"""

		start = time.time()
		batch = []
		inserted = 0
		for i in range(1, USERS_COUNT + 1):
			created_at = created_base + timedelta(minutes=5 * (i - 1))
			batch.append(
				(
					i,
					1000 + i,
					fake.first_name(),
					fake.last_name(),
					fake.email(),
					fake.numerify("###-###-####"),
					fake.credit_card_number(card_type=None),
					1 if random.random() < 0.7 else 0,
					created_at,
					updated_base,
				)
			)
			if len(batch) >= BATCH_SIZE:
				cursor.executemany(user_insert_sql, batch)
				conn.commit()
				inserted += len(batch)
				batch.clear()
				elapsed = time.time() - start
				print(f"Inserted {inserted}/{USERS_COUNT} users (elapsed {elapsed:.1f}s)")

		if batch:
			cursor.executemany(user_insert_sql, batch)
			conn.commit()
			inserted += len(batch)
			elapsed = time.time() - start
			print(f"Inserted {inserted}/{USERS_COUNT} users (elapsed {elapsed:.1f}s)")

		# Batch-insert stations with progress.
		station_insert_sql = f"""
			INSERT INTO {qualify('Stations')} (
				station_id,
				id,
				name,
				longitude,
				latitude,
				address,
				city,
				state,
				postal_code,
				capacity,
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
				:9,
				:10,
				:11,
				:12
			)
			"""

		batch = []
		inserted = 0
		start = time.time()
		for i in range(1, STATIONS_COUNT + 1):
			name, longitude, latitude = station_catalog[(i - 1) % len(station_catalog)]
			address = name
			city = "San Francisco"
			state = "CA"
			postal_code = "94103"
			capacity = random.randint(25, 60)
			batch.append(
				(
					i,
					i,
					name,
					round(longitude, 6),
					round(latitude, 6),
					address,
					city,
					state,
					postal_code,
					capacity,
					datetime(2026, 4, 1, 8, 0, 0),
					datetime(2026, 4, 20, 9, 0, 0),
				)
			)
			if len(batch) >= BATCH_SIZE:
				cursor.executemany(station_insert_sql, batch)
				conn.commit()
				inserted += len(batch)
				batch.clear()
				elapsed = time.time() - start
				print(f"Inserted {inserted}/{STATIONS_COUNT} stations (elapsed {elapsed:.1f}s)")

		if batch:
			cursor.executemany(station_insert_sql, batch)
			conn.commit()
			inserted += len(batch)
			elapsed = time.time() - start
			print(f"Inserted {inserted}/{STATIONS_COUNT} stations (elapsed {elapsed:.1f}s)")

		# Batch-insert bikes with progress.
		status_choices = ["available", "rented", "maintenance"]
		status_weights = [0.7, 0.2, 0.1]
		model_choices = ["Classic", "E-Bike"]

		bike_insert_sql = f"""
			INSERT INTO {qualify('Bikes')} (
				id,
				bike_id,
				brand,
				model,
				bike_type,
				status,
				station_id,
				purchased_at,
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
				:9,
				:10
			)
			"""

		batch = []
		inserted = 0
		start = time.time()
		for i in range(1, BIKES_COUNT + 1):
			model = random.choice(model_choices)
			status = random.choices(status_choices, weights=status_weights, k=1)[0]
			purchased_at = date.today() - timedelta(days=random.randint(120, 2000))
			batch.append(
				(
					i,
					2000 + i,
					"Golden Gate Gears",
					model,
					model,
					status,
					random.randint(1, STATIONS_COUNT),
					purchased_at,
					datetime(2026, 4, 2, 12, 0, 0),
					updated_base,
				)
			)
			if len(batch) >= BATCH_SIZE:
				cursor.executemany(bike_insert_sql, batch)
				conn.commit()
				inserted += len(batch)
				batch.clear()
				elapsed = time.time() - start
				print(f"Inserted {inserted}/{BIKES_COUNT} bikes (elapsed {elapsed:.1f}s)")

		if batch:
			cursor.executemany(bike_insert_sql, batch)
			conn.commit()
			inserted += len(batch)
			elapsed = time.time() - start
			print(f"Inserted {inserted}/{BIKES_COUNT} bikes (elapsed {elapsed:.1f}s)")

		cursor.execute(
			f"""
			UPDATE {qualify('Stations')} SET CAPACITY_AVAILABLE = CAPACITY - (
				SELECT COUNT(1) FROM {qualify('Bikes')} WHERE {qualify('Bikes')}.STATION_ID = {qualify('Stations')}.station_id AND STATUS = 'available'
			)
			"""
		)
		cursor.execute(
			f"""
			UPDATE {qualify('Stations')} SET BIKES_AVAILABLE = (
				SELECT COUNT(1) FROM {qualify('Bikes')} WHERE {qualify('Bikes')}.STATION_ID = {qualify('Stations')}.station_id AND STATUS = 'available'
			)
			"""
		)
		conn.commit()
	finally:
		cursor.close()
		conn.close()


if __name__ == "__main__":
	main()
