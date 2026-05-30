"""Functions for the hotel approval workflow.

Same event structure as the university room/key example
(Apply -> Department_approval -> CRS_approval -> Notify, keyed by application_id),
themed for a hotel:
  * Apply               -> a Guest submits a request
  * Department_approval -> a Front Desk staff member in the request's division
  * CRS_approval        -> a Manager
  * Notify              -> the guest is notified (AP iff both approvals AP)

Uses the generic ResourceCache via context["resource_cache"].

Requirements enforced (identical to the room/key example):
  * role-correct actor per event (Apply=Guest, Dept=FrontDesk, CRS=Manager)
  * Department approver is FrontDesk IN THE GUEST'S DIVISION
  * separation of duties: guest, front-desk approver, manager all distinct
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

	position_filter = None
	department_id = None
	if event_type == "Apply":
		position_filter = {"guest"}
	elif event_type == "Department_approval":
		position_filter = {"frontdesk"}
		applicant_id = _lookup_event_attribute(context, "Apply", application_id, "employee_id", required=True)
		applicant = _employee(cache, applicant_id)
		if applicant is not None:
			department_id = _norm_id(applicant.get("department_id"))
	elif event_type == "CRS_approval":
		position_filter = {"manager"}

	employees = cache.table("Employees")

	def matches(row):
		if position_filter is not None:
			if str(row.get("position", "")).lower() not in position_filter:
				return False
		if department_id is not None:
			if _norm_id(row.get("department_id")) != department_id:
				return False
		return True

	candidates = []
	for eid, row in employees.items():
		nid = _norm_id(eid)
		if nid is None or nid in excluded:
			continue
		if seeded_max_employee_id is not None and nid > seeded_max_employee_id:
			continue
		if matches(row):
			candidates.append(nid)

	if candidates and random.random() >= probability_new:
		return random.choice(candidates)

	return _insert_new_employee(cache, position_filter, department_id, excluded)


def _insert_new_employee(cache, position_filter, department_id, excluded):
	from faker import Faker
	faker = Faker()

	new_employee_id, new_pk = cache.next_ids("Employees")
	while _norm_id(new_employee_id) in excluded:
		new_employee_id, new_pk = cache.next_ids("Employees")

	_CANON = {"guest": "Guest", "frontdesk": "FrontDesk", "manager": "Manager"}
	if position_filter:
		token = next(iter(position_filter))
		position = _CANON.get(token, token.title())
	else:
		position = "Guest"

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
	dept_name = None
	if emp is not None and cache is not None:
		dept = cache.table("Departments").get(_norm_id(emp.get("department_id")))
		dept_name = dept.get("name") if dept else None

	purposes = [
		"requesting an early check-in for an arriving reservation",
		"requesting a late check-out for the current stay",
		"requesting a room upgrade for a booked reservation",
		"requesting additional housekeeping service for a room",
		"requesting access to a meeting or event space",
		"requesting a spa or wellness appointment booking",
		"requesting assistance with a maintenance issue in a room",
	]
	return (f"Guest is {random.choice(purposes)} "
	        f"handled by {dept_name or 'the relevant division'}.")


def generate_department_decision(context):
	return random.choices(["AP", "DN"], weights=[0.84, 0.16], k=1)[0]


def generate_department_comment(context):
	decision = context.get("attributes", {}).get("decision")
	approved = [
		"Front Desk confirms the request matches the reservation on file.",
		"Front Desk approves the request based on current availability.",
		"Front Desk verifies the guest is eligible for the requested service.",
		"Front Desk approves the request for the stated dates.",
	]
	denied = [
		"Front Desk denies the request because availability could not be confirmed.",
		"Front Desk cannot verify the reservation for this request.",
		"Front Desk denies the request because it falls outside policy.",
		"Front Desk requires additional details before approving.",
	]
	return random.choice(approved if decision == "AP" else denied)


def generate_crs_decision(context):
	return random.choices(["AP", "DN"], weights=[0.88, 0.12], k=1)[0]


def generate_crs_comment(context):
	decision = context.get("attributes", {}).get("decision")
	approved = [
		"Manager confirms the request is approved after review.",
		"Manager authorizes the service for the guest.",
		"Manager verifies the request complies with hotel policy.",
		"Manager approves and forwards the result for notification.",
	]
	denied = [
		"Manager denies the request because policy was not satisfied.",
		"Manager cannot authorize the request at this time.",
		"Manager denies the request pending further confirmation.",
		"Manager requires escalation before this can be approved.",
	]
	return random.choice(approved if decision == "AP" else denied)


def generate_notification_decision(context):
	attributes = context.get("attributes", {})
	application_id = attributes.get("application_id")
	dept = attributes.get("dept_decision")
	if dept is None or str(dept).startswith("NULL"):
		dept = _lookup_event_attribute(context, "Department_approval", application_id, "decision", required=True)
	crs = attributes.get("crs_decision")
	if crs is None or str(crs).startswith("NULL"):
		crs = _lookup_event_attribute(context, "CRS_approval", application_id, "decision", required=True)
	return "AP" if (dept == "AP" and crs == "AP") else "DN"
