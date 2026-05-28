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

# --- Scaled for ~187,500 applications (750,000 events at 4 events/application) ---
# Same structure as the university room/key example: a single Employees table
# with a position and a department (here themed as hotel divisions). Role
# coverage is sized so the division-match + separation-of-duties rules never
# starve and the 90% "existing approver" rate holds at this volume:
#   - FRONTDESK_PER_DIV "Front Desk" approvers in each division
#   - MANAGERS managers (the CRS-equivalent second approver)
#   - the remainder are Guest applicants
EMPLOYEES_COUNT = 8000
FRONTDESK_PER_DIV = 8
MANAGERS = 120
SEEDED_MAX_EMPLOYEE_ID = 1000 + EMPLOYEES_COUNT  # = 9000

SCHEMA_NAME = "appuser"
DROP_EXISTING = True

# The 8 "departments" are hotel divisions.
DEPARTMENT_ROWS = [
	(1, "Front Desk"),
	(2, "Housekeeping"),
	(3, "Concierge"),
	(4, "Food and Beverage"),
	(5, "Security"),
	(6, "Maintenance"),
	(7, "Events"),
	(8, "Spa and Wellness"),
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
	department_ids = [row[0] for row in DEPARTMENT_ROWS]
	rows: list[tuple] = []
	employee_id = 1001

	# Front Desk approvers: FRONTDESK_PER_DIV in every division (guarantees a
	# same-division approver exists for any guest, even after excluding the guest).
	for department_id in department_ids:
		for _ in range(FRONTDESK_PER_DIV):
			rows.append((employee_id, fake.name()[:40], "FrontDesk", department_id))
			employee_id += 1

	# Managers (CRS-equivalent second approver).
	for _ in range(MANAGERS):
		rows.append((employee_id, fake.name()[:40], "Manager", random.choice(department_ids)))
		employee_id += 1

	# Remaining employees are Guest applicants.
	while employee_id <= 1000 + EMPLOYEES_COUNT:
		rows.append((employee_id, fake.name()[:40], "Guest", random.choice(department_ids)))
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
		# batch insert
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

		print(f"Seeded {len(DEPARTMENT_ROWS)} divisions and {len(employee_rows)} employees "
		      f"({FRONTDESK_PER_DIV}/div Front Desk, {MANAGERS} Managers, rest Guests).")
	finally:
		cursor.close()
		conn.close()


if __name__ == "__main__":
	main()
