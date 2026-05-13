from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from faker import Faker

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from data_generator_engine.db_oracle import get_connection

SEED = 42
USERS_COUNT = 200
STATIONS_COUNT = 15
BIKES_COUNT = 65
SCHEMA_NAME = "appuser"
DROP_EXISTING = True
ISLA_VISTA_STATION_NAMES = [
	"Embarcadero del Norte & El Colegio Rd",
	"Embarcadero del Norte & El Greco Rd",
	"Embarcadero del Norte & Trigo Rd",
	"Embarcadero del Norte & Sabado Tarde Rd",
	"Embarcadero del Norte & Pardall Rd",
	"Embarcadero del Norte & Sueno Rd",
	"Embarcadero del Norte & Camino Pescadero",
	"Del Playa Dr & Camino Del Sur",
	"Del Playa Dr & Camino Corto",
	"Del Playa Dr & Camino Pescadero",
	"Camino Pescadero & Sabado Tarde Rd",
	"Camino Corto & El Colegio Rd",
	"El Colegio Rd & Camino Real",
	"El Colegio Rd & Embarcadero del Norte",
	"Sabado Tarde Rd & Camino Del Sur",
]
IV_BOUNDS = (-119.871, -119.846, 34.401, 34.420)


def qualify(table: str) -> str:
	return f"{SCHEMA_NAME}.{table}" if SCHEMA_NAME else table


def random_iv_coordinates() -> tuple[float, float]:
	lon_min, lon_max, lat_min, lat_max = IV_BOUNDS
	return (
		random.uniform(lon_min, lon_max),
		random.uniform(lat_min, lat_max),
	)


def load_station_catalog() -> list[tuple[str, float, float]]:
	return [(name, *random_iv_coordinates()) for name in ISLA_VISTA_STATION_NAMES]


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
					fake.numerify("###-###-####"),
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
			address = name
			city = "Isla Vista"
			state = "CA"
			postal_code = "93117"
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
		model_choices = ["Lemon-S", "Lemon-Gen4", "Lemon-S2"]
		bike_rows: list[tuple] = []
		for i in range(1, BIKES_COUNT + 1):
			model = random.choice(model_choices)
			status = random.choices(status_choices, weights=status_weights, k=1)[0]
			purchased_at = date.today() - timedelta(days=random.randint(120, 2000))
			bike_rows.append(
				(
					i,
					2000 + i,
					"Lemon",
					model,
					"Scooter",
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
