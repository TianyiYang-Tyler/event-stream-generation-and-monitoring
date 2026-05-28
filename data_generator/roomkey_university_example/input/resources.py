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

# --- Scaled for ~25,000 applications (100,000 events at 4 events/application) ---
# Role coverage is sized so that the department-match + separation-of-duties
# rules never deadlock and the 90% "existing approver" rate holds:
#   - ADVISORS_PER_DEPT advisors in each of the 8 departments
#   - CRS_COUNT campus-room-service approvers
#   - the remainder are Instructor/TA applicants
EMPLOYEES_COUNT = 3000
ADVISORS_PER_DEPT = 5
CRS_COUNT = 50
SEEDED_MAX_EMPLOYEE_ID = 1000 + EMPLOYEES_COUNT  # = 4000

SCHEMA_NAME = "appuser"
DROP_EXISTING = True

DEPARTMENT_ROWS = [
	(1, "Computer Science"),
	(2, "Statistics"),
	(3, "Mathematics"),
	(4, "Physics"),
	(5, "Chemistry"),
	(6, "Economics"),
	(7, "Engineering"),
	(8, "Biology"),
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

	# Advisors: ADVISORS_PER_DEPT in every department (guarantees a same-dept
	# approver exists for any applicant, even after excluding the applicant).
	for department_id in department_ids:
		for _ in range(ADVISORS_PER_DEPT):
			rows.append((employee_id, fake.name()[:40], "Advisor", department_id))
			employee_id += 1

	# CRS correspondents.
	for _ in range(CRS_COUNT):
		rows.append((employee_id, fake.name()[:40], "CRS", random.choice(department_ids)))
		employee_id += 1

	# Remaining employees are applicants (Instructor / TA).
	position_choices = ["Instructor", "TA"]
	position_weights = [0.45, 0.55]
	while employee_id <= 1000 + EMPLOYEES_COUNT:
		rows.append((
			employee_id,
			fake.name()[:40],
			random.choices(position_choices, weights=position_weights, k=1)[0],
			random.choice(department_ids),
		))
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
		cursor.executemany(
			f"""
			INSERT INTO {qualify('Employees')} (employee_id, name, position, department_id)
			VALUES (:1, :2, :3, :4)
			""",
			employee_rows,
		)

		conn.commit()
		print(f"Seeded {len(DEPARTMENT_ROWS)} departments and {len(employee_rows)} employees "
		      f"({ADVISORS_PER_DEPT}/dept advisors, {CRS_COUNT} CRS, rest applicants).")
	finally:
		cursor.close()
		conn.close()


if __name__ == "__main__":
	main()
