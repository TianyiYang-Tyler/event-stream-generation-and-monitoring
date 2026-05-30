"""Functions for the tech-company room-access approval workflow.

Same event structure as the university room/key example
(Apply -> Department_approval -> CRS_approval -> Notify, keyed by application_id),
themed for a global tech company (offices everywhere):
  * Apply               -> an Employee submits a room-access request
  * Department_approval -> a Facilities coordinator IN THE EMPLOYEE'S OFFICE
  * CRS_approval        -> a Security approver
  * Notify              -> the employee is notified (AP iff both approvals AP)

Uses the generic ResourceCache via context["resource_cache"].

Requirements enforced (identical to the room/key example):
  * role-correct actor per event (Apply=Employee, Dept=Facilities, CRS=Security)
  * Department approver is Facilities IN THE EMPLOYEE'S OFFICE
  * separation of duties: employee, facilities approver, security approver all distinct
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


def _position_key(position_filter):
	if not position_filter:
		return None
	return tuple(sorted(str(token) for token in position_filter))


def _get_employee_pool(cache, position_filter, department_id, seeded_max_employee_id):
	pool_cache = getattr(cache, "_employee_pool_cache", None)
	if pool_cache is None:
		pool_cache = {}
		cache._employee_pool_cache = pool_cache

	key = (_position_key(position_filter), department_id, seeded_max_employee_id)
	if key in pool_cache:
		return pool_cache[key]

	employees = cache.table("Employees")
	pool = []
	for eid, row in employees.items():
		nid = _norm_id(eid)
		if nid is None:
			continue
		if seeded_max_employee_id is not None and nid > seeded_max_employee_id:
			continue
		if position_filter is not None:
			if str(row.get("position", "")).lower() not in position_filter:
				continue
		if department_id is not None:
			if _norm_id(row.get("department_id")) != department_id:
				continue
		pool.append(nid)

	pool_cache[key] = pool
	return pool


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
		position_filter = {"employee"}
	elif event_type == "Department_approval":
		position_filter = {"facilities"}
		applicant_id = _lookup_event_attribute(context, "Apply", application_id, "employee_id", required=True)
		applicant = _employee(cache, applicant_id)
		if applicant is not None:
			department_id = _norm_id(applicant.get("department_id"))
	elif event_type == "CRS_approval":
		position_filter = {"security"}

	employees = cache.table("Employees")
	pool = _get_employee_pool(cache, position_filter, department_id, seeded_max_employee_id)

	if pool and random.random() >= probability_new:
		if not excluded:
			return random.choice(pool)
		# Avoid rebuilding the pool; filter excluded on-demand.
		for _ in range(10):
			candidate = random.choice(pool)
			if candidate not in excluded:
				return candidate
			# fall through to filtered list if random hits excluded repeatedly
			
		filtered = [candidate for candidate in pool if candidate not in excluded]
		if filtered:
			return random.choice(filtered)

	return _insert_new_employee(cache, position_filter, department_id, excluded)


def _insert_new_employee(cache, position_filter, department_id, excluded):
	from faker import Faker
	faker = Faker()

	new_employee_id, new_pk = cache.next_ids("Employees")
	while _norm_id(new_employee_id) in excluded:
		new_employee_id, new_pk = cache.next_ids("Employees")

	_CANON = {"employee": "Employee", "facilities": "Facilities", "security": "Security"}
	if position_filter:
		token = next(iter(position_filter))
		position = _CANON.get(token, token.title())
	else:
		position = "Employee"

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

	pool_cache = getattr(cache, "_employee_pool_cache", None)
	if isinstance(pool_cache, dict):
		pos_value = str(position).lower()
		for (pos_key, dept_key, seeded_max), pool in pool_cache.items():
			if pos_key is not None and pos_value not in pos_key:
				continue
			if dept_key is not None and _norm_id(department_id) != dept_key:
				continue
			if seeded_max is not None and _norm_id(new_employee_id) > seeded_max:
				continue
			pool.append(_norm_id(new_employee_id))

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
		"requesting badge access to a conference room",
		"requesting access to a lab or secure work area",
		"requesting after-hours access to a floor",
		"requesting a desk or hot-desk booking",
		"requesting access to a server or network room",
		"requesting access to an executive meeting room",
		"requesting temporary access for a visiting colleague",
	]
	return (f"Employee is {random.choice(purposes)} "
	        f"at the {dept_name or 'relevant'} office.")


def generate_department_decision(context):
	return random.choices(["AP", "DN"], weights=[0.84, 0.16], k=1)[0]


def generate_department_comment(context):
	decision = context.get("attributes", {}).get("decision")
	approved = [
		"Facilities confirms the request matches the employee's office record.",
		"Facilities approves the request based on current room availability.",
		"Facilities verifies the employee is eligible for the requested access.",
		"Facilities approves the request for the stated time window.",
	]
	denied = [
		"Facilities denies the request because room availability could not be confirmed.",
		"Facilities cannot verify the office record for this request.",
		"Facilities denies the request because it falls outside office policy.",
		"Facilities requires additional details before approving.",
	]
	return random.choice(approved if decision == "AP" else denied)


def generate_crs_decision(context):
	return random.choices(["AP", "DN"], weights=[0.88, 0.12], k=1)[0]


def generate_crs_comment(context):
	decision = context.get("attributes", {}).get("decision")
	approved = [
		"Security confirms the access request is approved after review.",
		"Security authorizes the access for the employee.",
		"Security verifies the request complies with corporate policy.",
		"Security approves and forwards the result for notification.",
	]
	denied = [
		"Security denies the request because access policy was not satisfied.",
		"Security cannot authorize the access request at this time.",
		"Security denies the request pending further confirmation.",
		"Security requires escalation before this can be approved.",
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
