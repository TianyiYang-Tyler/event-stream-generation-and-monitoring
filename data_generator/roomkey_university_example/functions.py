"""Functions for the university room/key access approval workflow.

Pipeline per application_id: Apply -> Department_approval -> CRS_approval -> Notify.

Uses the generic ResourceCache via context["resource_cache"]:
  cache.table("Employees")   -> {employee_id: {employee_id, name, position, department_id}}
  cache.table("Departments") -> {did: {did, name}}
  cache.next_ids("Employees"), cache.add_row("Employees", {...})

Requirements enforced:
  * role-correct actor per event (Apply=Instructor/TA, Dept=Advisor, CRS=CRS)
  * Department approver is an Advisor IN THE APPLICANT'S DEPARTMENT
  * separation of duties: applicant, dept approver, CRS approver all distinct
  * comments consistent with the decision
  * Notify.decision = AP iff both Department and CRS decisions are AP
"""

import random


# ---------------------------------------------------------------- helpers
def _norm_id(value):
	if value is None:
		return None
	try:
		return int(value)
	except (TypeError, ValueError):
		text = str(value).strip()
		if text.startswith("NULL"):
			return None
		try:
			return int(text)
		except ValueError:
			return None


def _current_event_type(context):
	for key in ("event_type", "event_name", "type", "current_event_type"):
		value = context.get(key)
		if value:
			return str(value)
	event = context.get("event")
	if isinstance(event, dict):
		for key in ("type", "name", "event_type"):
			value = event.get(key)
			if value:
				return str(value)
	return ""


def _lookup_event_attribute(context, event_type, application_id, attribute, required=False):
	"""Read an already-filled attribute from another event in the same application."""
	runtime_state = context.get("runtime_state")
	attributes = context.get("attributes", {})
	if runtime_state is None or application_id is None:
		if required:
			raise KeyError(f"{event_type}.{attribute} requires application_id and runtime_state")
		return None
	match_attributes = dict(attributes)
	match_attributes["application_id"] = application_id
	match_key = runtime_state.build_key(match_attributes, ["application_id"])
	try:
		return runtime_state.lookup(event_type, ["application_id"], match_key, attribute)
	except KeyError:
		if required:
			raise
		return None


def _employee(cache, employee_id):
	eid = _norm_id(employee_id)
	if eid is None:
		return None
	emp = cache.table("Employees")
	row = emp.get(eid)
	if row is None:
		row = emp.get(str(eid))
	return row


def _excluded_ids(context, event_type, application_id):
	"""Ids that must NOT be reused on this application (separation of duties)."""
	excluded = set()
	if application_id is None:
		return excluded
	if event_type == "Department_approval":
		sources = ("Apply", "CRS_approval")
	elif event_type == "CRS_approval":
		sources = ("Apply", "Department_approval")
	else:
		sources = ()
	for src in sources:
		val = _lookup_event_attribute(context, src, application_id, "employee_id", required=False)
		nid = _norm_id(val)
		if nid is not None:
			excluded.add(nid)
	return excluded


# ---------------------------------------------------------------- employee_id
def choose_or_generate_employee(context, probability_new=0.1, seeded_max_employee_id=None):
	cache = context.get("resource_cache")
	if cache is None:
		raise RuntimeError("resource_cache not available in context")

	attributes = context.get("attributes", {})
	event_type = _current_event_type(context)
	application_id = attributes.get("application_id")

	excluded = _excluded_ids(context, event_type, application_id)

	# role + department filters by event type
	position_filter = None
	department_id = None
	if event_type == "Apply":
		position_filter = {"instructor", "ta"}
	elif event_type == "Department_approval":
		position_filter = {"advisor"}
		applicant_id = _lookup_event_attribute(context, "Apply", application_id, "employee_id", required=True)
		applicant = _employee(cache, applicant_id)
		if applicant is not None:
			department_id = _norm_id(applicant.get("department_id"))
	elif event_type == "CRS_approval":
		position_filter = {"crs"}

	employees = cache.table("Employees")

	def matches(row):
		if position_filter is not None:
			pos = str(row.get("position", "")).lower()
			if pos not in position_filter:
				return False
		if department_id is not None:
			if _norm_id(row.get("department_id")) != department_id:
				return False
		return True

	candidates = [
		_norm_id(eid) for eid, row in employees.items()
		if matches(row)
		and (seeded_max_employee_id is None or _norm_id(eid) is None or _norm_id(eid) <= seeded_max_employee_id)
		and _norm_id(eid) not in excluded
	]
	candidates = [c for c in candidates if c is not None]

	if candidates and random.random() >= probability_new:
		return random.choice(candidates)

	# mint a new employee of the required role (and department, if constrained)
	return _insert_new_employee(cache, position_filter, department_id, excluded)


def _insert_new_employee(cache, position_filter, department_id, excluded):
	from faker import Faker
	faker = Faker()

	new_employee_id, new_pk = cache.next_ids("Employees")
	while _norm_id(new_employee_id) in excluded:
		new_employee_id, new_pk = cache.next_ids("Employees")

	# Map the lowercase filter token to the canonical seeded position spelling.
	_CANON = {"instructor": "Instructor", "ta": "TA", "advisor": "Advisor", "crs": "CRS"}
	if position_filter:
		token = next(iter(position_filter))
		position = _CANON.get(token, token.title())
	else:
		position = "Instructor"

	if department_id is None:
		dept_ids = [_norm_id(d) for d in cache.table("Departments").keys()]
		dept_ids = [d for d in dept_ids if d is not None]
		department_id = random.choice(dept_ids) if dept_ids else 1

	row = {
		"employee_id": new_employee_id,
		"name": faker.name()[:40],
		"position": position,
		"department_id": department_id,
	}
	cache.add_row("Employees", row)
	cache.mark_dirty("Employees", new_employee_id)
	return new_employee_id


# ---------------------------------------------------------------- details/comments
def generate_application_details(context):
	cache = context.get("resource_cache")
	attributes = context.get("attributes", {})
	emp = _employee(cache, attributes.get("employee_id")) if cache else None
	position = emp.get("position") if emp else None
	dept_name = None
	if emp is not None and cache is not None:
		dept = cache.table("Departments").get(_norm_id(emp.get("department_id")))
		dept_name = dept.get("name") if dept else None

	purposes = [
		"accessing a classroom for scheduled teaching duties",
		"holding office hours in a department-managed room",
		"preparing course materials before class",
		"supporting a discussion section or lab session",
		"accessing instructional equipment for a course",
		"proctoring or setting up an exam",
	]
	if position:
		return (f"{str(position).title()} requests room access for "
		        f"{random.choice(purposes)} in {dept_name or 'the department'}.")
	return f"Employee requests room access for {random.choice(purposes)}."


def generate_department_decision(context):
	return random.choices(["AP", "DN"], weights=[0.84, 0.16], k=1)[0]


def generate_department_comment(context):
	decision = context.get("attributes", {}).get("decision")
	approved = [
		"Department confirms the request is related to teaching or TA duties.",
		"Department approves access based on the stated instructional purpose.",
		"Department verifies that the applicant has a valid need for room access.",
		"Department approves the request for the requested room access period.",
	]
	denied = [
		"Department denies the request because the purpose needs more justification.",
		"Department cannot verify the stated need for room access.",
		"Department denies the request because the applicant is not assigned to the room.",
		"Department requires additional information before approving access.",
	]
	return random.choice(approved if decision == "AP" else denied)


def generate_crs_decision(context):
	return random.choices(["AP", "DN"], weights=[0.88, 0.12], k=1)[0]


def generate_crs_comment(context):
	decision = context.get("attributes", {}).get("decision")
	approved = [
		"CRS confirms the room access request is valid.",
		"CRS approves key access after checking room service records.",
		"CRS verifies that the requested room can be assigned.",
		"CRS approves access and forwards the result for notification.",
	]
	denied = [
		"CRS denies the request because the room access policy was not satisfied.",
		"CRS cannot approve access for the requested room at this time.",
		"CRS denies the request because the room assignment could not be verified.",
		"CRS requires further confirmation before key access can be granted.",
	]
	return random.choice(approved if decision == "AP" else denied)


def generate_notification_decision(context):
	attributes = context.get("attributes", {})
	application_id = attributes.get("application_id")
	# Prefer the decisions copied onto the Notify event (dept_decision /
	# crs_decision); fall back to a cross-event lookup if not present.
	dept = attributes.get("dept_decision")
	if dept is None or str(dept).startswith("NULL"):
		dept = _lookup_event_attribute(context, "Department_approval", application_id, "decision", required=True)
	crs = attributes.get("crs_decision")
	if crs is None or str(crs).startswith("NULL"):
		crs = _lookup_event_attribute(context, "CRS_approval", application_id, "decision", required=True)
	return "AP" if (dept == "AP" and crs == "AP") else "DN"
