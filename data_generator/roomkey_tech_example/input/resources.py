from __future__ import annotations

import random
import sys
from pathlib import Path

from faker import Faker

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from data_generator_engine.db_oracle import get_connection

SEED = 42

# --- Scaled for ~250,000 applications (1,000,000 events at 4 events/application) ---
# Same structure as the university room/key example: a single Employees table
# with a position and a department (here themed as global OFFICES). A room
# request is approved by Facilities staff AT THE SAME OFFICE, then by Security.
# Role coverage is sized so the office-match + separation-of-duties rules never
# starve and the 90% "existing approver" rate holds at 1M-event volume:
#   - FACILITIES_PER_OFFICE Facilities approvers in each office
#   - SECURITY_COUNT Security approvers (the CRS-equivalent second approver)
#   - the remainder are Employee applicants
EMPLOYEES_COUNT = 30000
FACILITIES_PER_OFFICE = 20
SECURITY_COUNT = 300
SEEDED_MAX_EMPLOYEE_ID = 1000 + EMPLOYEES_COUNT  # = 31000

SCHEMA_NAME = "appuser"
DROP_EXISTING = True

# The 8 "departments" are global offices of the tech company.
DEPARTMENT_ROWS = [
	(1, "San Francisco"),
	(2, "New York"),
	(3, "London"),
	(4, "Dublin"),
	(5, "Berlin"),
	(6, "Bangalore"),
	(7, "Tokyo"),
	(8, "Sydney"),
]


def qualify(table: str) -> str:
	return f"{SCHEMA_NAME}.{table}" if SCHEMA_NAME else table


def create_tables(cursor) -> None:
	statements = [
		f"""
		CREATE TABLE {qualify('Departments')} (
			did NUMBER(10) PRIMARY KEY,
			name VARCHAR2(40) NOT NULL
		)
		""",
		f"""
		CREATE TABLE {qualify('Employees')} (
			employee_id NUMBER(10) PRIMARY KEY,
			name VARCHAR2(40) NOT NULL,
			position VARCHAR2(20) NOT NULL,
			department_id NUMBER(10) NOT NULL,
			CONSTRAINT fk_employees_department
				FOREIGN KEY (department_id) REFERENCES {qualify('Departments')}(did)
		)
		""",
	]
	for statement in statements:
		try:
			cursor.execute(statement)
		except Exception as exc:
			if "ORA-00955" not in str(exc):  # name already used by an existing object
				raise


def drop_tables(cursor) -> None:
	statements = [
		f"DROP TABLE {qualify('Employees')} CASCADE CONSTRAINTS",
		f"DROP TABLE {qualify('Departments')} CASCADE CONSTRAINTS",
	]
	for statement in statements:
		try:
			cursor.execute(statement)
		except Exception as exc:
			if "ORA-00942" not in str(exc):  # table or view does not exist
				raise


def build_employee_rows() -> list[tuple]:
	fake = Faker()
	office_ids = [row[0] for row in DEPARTMENT_ROWS]
	rows: list[tuple] = []
	employee_id = 1001

	# Facilities approvers: FACILITIES_PER_OFFICE in every office (guarantees a
	# same-office approver exists for any employee, even after excluding them).
	for office_id in office_ids:
		for _ in range(FACILITIES_PER_OFFICE):
			rows.append((employee_id, fake.name()[:40], "Facilities", office_id))
			employee_id += 1

	# Security approvers (CRS-equivalent second approver), spread across offices.
	for _ in range(SECURITY_COUNT):
		rows.append((employee_id, fake.name()[:40], "Security", random.choice(office_ids)))
		employee_id += 1

	# Remaining employees are applicants requesting room access.
	while employee_id <= 1000 + EMPLOYEES_COUNT:
		rows.append((employee_id, fake.name()[:40], "Employee", random.choice(office_ids)))
		employee_id += 1

	return rows


def main() -> None:
	Faker.seed(SEED)
	random.seed(SEED)

	conn = get_connection()
	cursor = conn.cursor()

	try:
		if DROP_EXISTING:
			drop_tables(cursor)
		create_tables(cursor)

		cursor.executemany(
			f"INSERT INTO {qualify('Departments')} (did, name) VALUES (:1, :2)",
			DEPARTMENT_ROWS,
		)

		employee_rows = build_employee_rows()
		BATCH = 5000
		for i in range(0, len(employee_rows), BATCH):
			cursor.executemany(
				f"""
				INSERT INTO {qualify('Employees')} (employee_id, name, position, department_id)
				VALUES (:1, :2, :3, :4)
				""",
				employee_rows[i:i + BATCH],
			)
			conn.commit()

		print(f"Seeded {len(DEPARTMENT_ROWS)} offices and {len(employee_rows)} employees "
		      f"({FACILITIES_PER_OFFICE}/office Facilities, {SECURITY_COUNT} Security, rest Employees).")
	finally:
		cursor.close()
		conn.close()


if __name__ == "__main__":
	main()
