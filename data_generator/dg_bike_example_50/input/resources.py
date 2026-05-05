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
USERS_COUNT = 100
STATIONS_COUNT = 100
BIKES_COUNT = 1000
SCHEMA_NAME = "appuser"
DROP_EXISTING = True
STATION_INFO_URL = "https://gbfs.citibikenyc.com/gbfs/en/station_information.json"
NYC_STATION_NAMES = [
	"W 21 St & 6 Ave",
	"E 17 St & Broadway",
	"8 Ave & W 31 St",
	"W 33 St & 7 Ave",
	"W 52 St & 5 Ave",
	"Broadway & W 60 St",
	"Central Park S & 6 Ave",
	"W 41 St & 8 Ave",
	"E 20 St & Park Ave",
	"E 24 St & Park Ave S",
	"E 30 St & Park Ave S",
	"E 42 St & Vanderbilt Ave",
	"Lexington Ave & E 24 St",
	"E 47 St & Park Ave",
	"E 55 St & Lexington Ave",
	"W 4 St & 7 Ave S",
	"Perry St & Bleecker St",
	"Christopher St & Greenwich St",
	"Hudson St & Reade St",
	"West St & Chambers St",
	"Franklin St & W Broadway",
	"Lafayette St & E 8 St",
	"E 6 St & Avenue B",
	"Avenue C & E 5 St",
	"E 14 St & Avenue B",
	"E 10 St & Avenue A",
	"1 Ave & E 16 St",
	"2 Ave & E 32 St",
	"Pershing Square North",
	"Union Square East",
	"Broadway & W 24 St",
	"Broadway & W 29 St",
	"Broadway & W 36 St",
	"Broadway & W 49 St",
	"Broadway & W 51 St",
	"Broadway & W 53 St",
	"Broadway & W 58 St",
	"Broadway & W 62 St",
	"Broadway & W 68 St",
	"5 Ave & E 29 St",
	"5 Ave & E 41 St",
	"5 Ave & E 44 St",
	"5 Ave & E 48 St",
	"5 Ave & E 53 St",
	"5 Ave & E 63 St",
	"6 Ave & W 34 St",
	"6 Ave & W 45 St",
	"6 Ave & W 57 St",
	"7 Ave & W 18 St",
	"7 Ave & W 26 St",
	"7 Ave & W 33 St",
	"7 Ave & W 42 St",
	"7 Ave & W 55 St",
	"8 Ave & W 33 St",
	"8 Ave & W 38 St",
	"8 Ave & W 52 St",
	"8 Ave & W 56 St",
	"8 Ave & W 59 St",
	"9 Ave & W 22 St",
	"9 Ave & W 28 St",
	"9 Ave & W 45 St",
	"10 Ave & W 28 St",
	"10 Ave & W 46 St",
	"10 Ave & W 50 St",
	"11 Ave & W 27 St",
	"11 Ave & W 59 St",
	"E 2 St & Avenue C",
	"E 3 St & Avenue B",
	"E 5 St & Avenue C",
	"E 7 St & Avenue A",
	"E 9 St & Avenue C",
	"E 11 St & Broadway",
	"E 12 St & 3 Ave",
	"E 13 St & Avenue A",
	"E 15 St & 3 Ave",
	"E 16 St & Irving Pl",
	"E 18 St & 3 Ave",
	"E 19 St & 3 Ave",
	"E 20 St & 2 Ave",
	"E 22 St & 2 Ave",
	"E 23 St & 1 Ave",
	"E 25 St & 2 Ave",
	"E 27 St & 1 Ave",
	"E 28 St & 3 Ave",
	"E 31 St & 3 Ave",
	"E 33 St & 2 Ave",
	"E 34 St & 2 Ave",
	"E 35 St & 3 Ave",
	"E 36 St & 2 Ave",
	"E 37 St & 2 Ave",
	"E 39 St & 2 Ave",
	"E 40 St & Park Ave",
	"E 43 St & 2 Ave",
	"E 45 St & 3 Ave",
	"E 51 St & 1 Ave",
	"E 53 St & 3 Ave",
	"E 57 St & 1 Ave",
	"E 58 St & 3 Ave",
	"E 60 St & York Ave",
	"E 62 St & 3 Ave",
	"E 63 St & 3 Ave",
	"E 67 St & Park Ave",
	"E 72 St & York Ave",
	"E 74 St & 1 Ave",
	"E 79 St & 1 Ave",
	"E 81 St & Park Ave",
	"E 84 St & 1 Ave",
	"E 88 St & 1 Ave",
	"W 10 St & 5 Ave",
	"W 11 St & 6 Ave",
	"W 12 St & W 4 St",
	"W 13 St & 7 Ave",
	"W 14 St & 7 Ave",
	"W 15 St & 6 Ave",
	"W 16 St & 8 Ave",
	"W 18 St & 6 Ave",
	"W 20 St & 11 Ave",
	"W 22 St & 10 Ave",
	"W 23 St & 10 Ave",
	"W 24 St & 7 Ave",
	"W 25 St & 10 Ave",
	"W 26 St & 8 Ave",
	"W 27 St & 10 Ave",
	"W 28 St & 7 Ave",
	"W 30 St & 10 Ave",
	"W 31 St & 7 Ave",
	"W 34 St & 11 Ave",
	"W 37 St & 10 Ave",
	"W 38 St & 9 Ave",
	"W 39 St & 9 Ave",
	"W 40 St & 8 Ave",
	"W 42 St & 8 Ave",
	"W 43 St & 10 Ave",
	"W 44 St & 9 Ave",
	"W 45 St & 8 Ave",
	"W 46 St & 11 Ave",
	"W 47 St & 9 Ave",
	"W 48 St & 9 Ave",
	"W 50 St & 9 Ave",
	"W 51 St & 6 Ave",
	"W 54 St & 9 Ave",
	"W 56 St & 6 Ave",
	"W 57 St & 6 Ave",
	"W 59 St & 10 Ave",
	"W 63 St & Broadway",
	"W 67 St & Broadway",
	"W 70 St & Broadway",
	"W 72 St & Broadway",
	"W 74 St & Columbus Ave",
	"W 77 St & Columbus Ave",
	"W 79 St & Broadway",
	"W 81 St & Central Park W",
	"W 83 St & Broadway",
	"W 84 St & Columbus Ave",
	"W 86 St & Broadway",
	"W 87 St & West End Ave",
	"W 89 St & Columbus Ave",
	"W 90 St & West End Ave",
	"W 92 St & Broadway",
	"W 94 St & Columbus Ave",
	"W 96 St & Broadway",
	"W 98 St & Columbus Ave",
	"W 100 St & Broadway",
	"W 102 St & Columbus Ave",
	"W 104 St & Broadway",
	"W 106 St & Columbus Ave",
	"W 110 St & Amsterdam Ave",
	"Lenox Ave & W 111 St",
	"Lenox Ave & W 116 St",
	"Adam Clayton Powell Blvd & W 125 St",
	"Frederick Douglass Blvd & W 125 St",
	"St Nicholas Ave & W 126 St",
	"Columbus Ave & W 72 St",
	"Columbus Ave & W 95 St",
	"Riverside Dr & W 72 St",
	"Riverside Dr & W 80 St",
	"Riverside Dr & W 104 St",
	"South St & Whitehall St",
	"Front St & Maiden Ln",
	"Water St & Fletcher St",
	"Pearl St & Hanover Sq",
	"Wall St & Water St",
	"South End Ave & Liberty St",
	"Battery Pl & Greenwich St",
	"West Thames St",
	"Vesey Pl & River Terrace",
	"Liberty St & Broadway",
	"Reade St & Broadway",
	"Centre St & Chambers St",
	"Mott St & Prince St",
	"Mulberry St & Grand St",
	"Elizabeth St & Hester St",
	"Allen St & Stanton St",
	"Orchard St & Canal St",
	"Pitt St & Stanton St",
	"Essex St & Rivington St",
	"Clinton St & Grand St",
	"Forsyth St & Broome St",
	"Bowery & E 4 St",
	"Bowery & E Houston St",
	"Spring St & Crosby St",
	"Prince St & Mercer St",
	"Broadway & Spring St",
	"Greene St & W Houston St",
	"Mercer St & Bleecker St",
	"W Broadway & Spring St",
	"Hudson St & N Moore St",
	"Varick St & N Moore St",
	"6 Ave & W 16 St",
	"6 Ave & W 21 St",
	"6 Ave & W 26 St",
	"7 Ave S & Christopher St",
	"Greenwich Ave & 8 Ave",
	"Washington Pl & 6 Ave",
	"MacDougal St & Prince St",
	"University Pl & E 8 St",
	"University Pl & E 14 St",
	"University Pl & E 13 St",
	"Mercer St & Spring St",
	"1 Ave & E 30 St",
	"2 Ave & E 58 St",
	"3 Ave & E 72 St",
	"Lexington Ave & E 63 St",
	"Madison Ave & E 33 St",
	"Madison Ave & E 42 St",
	"Madison Ave & E 51 St",
	"Madison Ave & E 82 St",
	"Park Ave & E 42 St",
	"Park Ave & E 68 St",
	"York Ave & E 72 St",
]
NYC_BOUNDS = (-74.25909, -73.70018, 40.477399, 40.917577)


def qualify(table: str) -> str:
	return f"{SCHEMA_NAME}.{table}" if SCHEMA_NAME else table


def random_nyc_coordinates() -> tuple[float, float]:
	lon_min, lon_max, lat_min, lat_max = NYC_BOUNDS
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

	return [(name, *random_nyc_coordinates()) for name in NYC_STATION_NAMES]


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

		user_rows: list[tuple] = []
		for i in range(1, USERS_COUNT + 1):
			created_at = created_base + timedelta(minutes=5 * (i - 1))
			user_rows.append(
				(
					i,
					1000 + i,
					fake.first_name(),
					fake.last_name(),
					fake.email(),
					fake.phone_number(),
					fake.credit_card_number(card_type=None),
					1 if random.random() < 0.7 else 0,
					created_at,
					updated_base,
				)
			)

		cursor.executemany(
			f"""
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
			""",
			user_rows,
		)

		station_rows: list[tuple] = []
		for i in range(1, STATIONS_COUNT + 1):
			name, longitude, latitude = station_catalog[(i - 1) % len(station_catalog)]
			address = fake.street_address()
			city = "New York"
			state = "NY"
			postal_code = "10001"
			capacity = random.randint(25, 60)
			station_rows.append(
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

		cursor.executemany(
			f"""
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
			""",
			station_rows,
		)

		status_choices = ["available", "rented", "maintenance"]
		status_weights = [0.7, 0.2, 0.1]
		model_choices = ["Classic", "E-Bike"]
		bike_rows: list[tuple] = []
		for i in range(1, BIKES_COUNT + 1):
			model = random.choice(model_choices)
			status = random.choices(status_choices, weights=status_weights, k=1)[0]
			purchased_at = date.today() - timedelta(days=random.randint(120, 2000))
			bike_rows.append(
				(
					i,
					2000 + i,
					"Citi Bike",
					model,
					model,
					status,
					random.randint(1, STATIONS_COUNT),
					purchased_at,
					datetime(2026, 4, 2, 12, 0, 0),
					updated_base,
				)
			)

		cursor.executemany(
			f"""
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
			""",
			bike_rows,
		)

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
