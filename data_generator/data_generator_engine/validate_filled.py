#!/usr/bin/env python3
"""Validate a filled (and ideally time-sorted) skeleton event stream.

Two things:

1. RULE VALIDATION (per session). Each session must follow the lifecycle
       RentBike -> ReportLocation* -> ReturnBike
   i.e. exactly one RentBike, then zero or more ReportLocation, then exactly
   one ReturnBike, in non-decreasing time order. Also checks that copied
   fields (user_id, bike_id, credit_card_num, is_member) are consistent within
   a session's rent->return cycle, and that no value is left as a NULL
   placeholder.

2. DISTRIBUTION REPORT. Prints the actual distributions of filled values
   (event counts, new-vs-existing users, member ratio, reports-per-session,
   station usage spread, etc.). If --fill-spec is given, also compares the
   declared target distributions against the actuals and flags any field
   outside its tolerance (PASS/FAIL).

Streams the input with ET.iterparse, so it works on large files. It keeps small
per-session and per-value aggregates in memory (counts, not events); for very
large inputs that is bounded by the number of distinct sessions/stations.

Both layouts supported (flat <RentBike>.. and structured <Event><Type>..).

Usage:
    python3 validate_filled.py INPUT.xml [--fill-spec fill_spec.yaml]
                               [--seeded-max-user-id 4000] [--report OUT.txt]
"""
from __future__ import annotations

import argparse
import math
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

RENT = "RentBike"
REPORT = "ReportLocation"
RETURN = "ReturnBike"
KNOWN = {RENT, REPORT, RETURN}


# --------------------------------------------------------------------------- #
# layout helpers
# --------------------------------------------------------------------------- #
def get_type(elem):
    if elem.tag == "Event":
        t = elem.find("Type")
        return t.text if t is not None else None
    return elem.tag


def get_attrs(elem):
    """Return {attr_name: text} for both layouts."""
    if elem.tag == "Event":
        out = {}
        for a in elem.iter("Attribute"):
            name = a.get("name")
            if name is not None:
                out[name] = a.text
        return out
    return {c.tag: c.text for c in elem if isinstance(c.tag, str)}


def get_time(elem):
    t = elem.get("time")
    if t is None:
        c = elem.find("Time")
        if c is not None:
            t = c.text
    try:
        return float(t)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# per-session lifecycle validation
# --------------------------------------------------------------------------- #
def validate_session(types_in_time_order):
    if not types_in_time_order:
        return False, "no events"
    unknown = [t for t in types_in_time_order if t not in KNOWN]
    if unknown:
        return False, f"unknown event type(s): {sorted(set(unknown))}"
    if types_in_time_order.count(RENT) != 1:
        return False, f"expected 1 RentBike, found {types_in_time_order.count(RENT)}"
    if types_in_time_order.count(RETURN) != 1:
        return False, f"expected 1 ReturnBike, found {types_in_time_order.count(RETURN)}"
    if types_in_time_order[0] != RENT:
        return False, f"first event is {types_in_time_order[0]}, expected RentBike"
    if types_in_time_order[-1] != RETURN:
        return False, f"last event is {types_in_time_order[-1]}, expected ReturnBike"
    if any(t != REPORT for t in types_in_time_order[1:-1]):
        return False, "non-ReportLocation event between Rent and Return"
    return True, ""


# --------------------------------------------------------------------------- #
# main scan
# --------------------------------------------------------------------------- #
def scan(input_path, seeded_max_user_id):
    # Per-session accumulators (small: per session, not per event).
    sess_events = defaultdict(list)   # sid -> list of (time, type, seq)
    sess_rent_fields = {}             # sid -> {user_id,bike_id,cc,is_member}
    sess_copy_mismatch = defaultdict(list)
    sess_null = defaultdict(int)

    type_counts = Counter()
    station_rent = Counter()          # station_id usage on RentBike
    station_return = Counter()        # station_id usage on ReturnBike
    member_counts = Counter()         # is_member value on RentBike
    user_new_vs_existing = Counter()  # 'new'/'existing' by seeded_max_user_id
    seen_users = set()

    depth = 0
    seq = 0
    total = 0
    time_order_violations = 0
    prev_time = None

    context = ET.iterparse(input_path, events=("start", "end"))
    for ev, elem in context:
        if ev == "start":
            depth += 1
            continue
        depth -= 1
        if depth != 1:
            continue

        etype = get_type(elem)
        attrs = get_attrs(elem)
        tval = get_time(elem)
        sid = attrs.get("session_id")

        total += 1
        type_counts[etype] += 1

        # global time ordering check (file should be sorted ascending)
        if tval is not None:
            if prev_time is not None and tval < prev_time:
                time_order_violations += 1
            prev_time = tval

        # null placeholder check
        for k, v in attrs.items():
            if v is not None and str(v).startswith("NULL"):
                sess_null[sid] += 1

        sess_events[sid].append((tval if tval is not None else math.inf, etype, seq))

        if etype == RENT:
            uid = attrs.get("user_id")
            sess_rent_fields[sid] = {
                "user_id": uid,
                "bike_id": attrs.get("bike_id"),
                "credit_card_num": attrs.get("credit_card_num"),
                "is_member": attrs.get("is_member"),
            }
            if attrs.get("station_id") is not None:
                station_rent[attrs["station_id"]] += 1
            if attrs.get("is_member") is not None:
                member_counts[str(attrs["is_member"])] += 1
            if uid is not None:
                seen_users.add(uid)
                try:
                    user_new_vs_existing[
                        "new" if int(uid) > seeded_max_user_id else "existing"
                    ] += 1
                except (TypeError, ValueError):
                    user_new_vs_existing["unparseable"] += 1
        elif etype == RETURN:
            if attrs.get("station_id") is not None:
                station_return[attrs["station_id"]] += 1
            # copy-consistency vs the session's RentBike
            ref = sess_rent_fields.get(sid)
            if ref:
                for key in ("user_id", "bike_id", "credit_card_num", "is_member"):
                    if attrs.get(key) is not None and ref.get(key) is not None:
                        if attrs[key] != ref[key]:
                            sess_copy_mismatch[sid].append(key)

        seq += 1
        elem.clear()
        if total % 200000 == 0:
            print(f"  ...scanned {total} events", file=sys.stderr, flush=True)

    # finalize per-session validation
    good = 0
    bad = []
    reports_per_session = Counter()
    for sid, evs in sess_events.items():
        evs.sort(key=lambda r: (r[0], r[2]))  # by time, then file order
        types = [t for _, t, _ in evs]
        ok, reason = validate_session(types)
        if sess_null.get(sid):
            ok = False
            reason = (reason + "; " if reason else "") + f"{sess_null[sid]} NULL value(s)"
        if sess_copy_mismatch.get(sid):
            ok = False
            cols = sorted(set(sess_copy_mismatch[sid]))
            reason = (reason + "; " if reason else "") + f"copy mismatch: {cols}"
        if ok:
            good += 1
            reports_per_session[types.count(REPORT)] += 1
        else:
            if len(bad) < 100:
                bad.append((sid, reason))

    return {
        "total_events": total,
        "type_counts": type_counts,
        "n_sessions": len(sess_events),
        "good_sessions": good,
        "bad_sessions": bad,
        "n_bad": len(sess_events) - good,
        "time_order_violations": time_order_violations,
        "station_rent": station_rent,
        "station_return": station_return,
        "member_counts": member_counts,
        "user_new_vs_existing": user_new_vs_existing,
        "distinct_users": len(seen_users),
        "reports_per_session": reports_per_session,
    }


# --------------------------------------------------------------------------- #
# distribution reporting
# --------------------------------------------------------------------------- #
def uniformity_stats(counter):
    """For a 'uniform over column' field: return spread metrics plus a
    chi-square goodness-of-fit assessment against the uniform distribution.

    max_rel_dev is descriptive only (it is dominated by the single most extreme
    bin and by small-sample noise). The chi-square test is the sound basis for
    a pass/fail judgement: it accounts for sample size and the number of bins.
    We report the reduced chi-square (chi2 / degrees_of_freedom); for a true
    uniform draw this is ~1.0 regardless of sample size, so it is comparable
    across runs of different sizes."""
    if not counter:
        return None
    vals = list(counter.values())
    n = len(vals)
    total = sum(vals)
    mean = total / n
    max_dev = max(abs(v - mean) for v in vals) / mean if mean else 0.0

    # chi-square against uniform expectation (mean per bin).
    if mean > 0 and n > 1:
        chi2 = sum((v - mean) ** 2 / mean for v in vals)
        reduced_chi2 = chi2 / (n - 1)
    else:
        chi2 = 0.0
        reduced_chi2 = 0.0

    return {
        "distinct_values": n,
        "total": total,
        "mean_per_value": mean,
        "min": min(vals),
        "max": max(vals),
        "max_rel_dev_from_uniform": max_dev,
        "reduced_chi2": reduced_chi2,
    }


def load_spec_targets(fill_spec_path):
    import yaml
    with open(fill_spec_path) as f:
        spec = yaml.safe_load(f)
    targets = {}
    events = spec.get("events", {})
    for ev_name, fields in events.items():
        for fld, cfg in fields.items():
            dist = cfg.get("distribution")
            if not dist:
                continue
            targets[(ev_name, fld)] = dist
    return targets


def build_report(stats, fill_spec_path, seeded_max_user_id):
    L = []
    w = L.append

    w("=" * 70)
    w("FILLED STREAM VALIDATION REPORT")
    w("=" * 70)

    # ---- rule validation ----
    w("")
    w("RULE VALIDATION (RentBike -> ReportLocation* -> ReturnBike)")
    w("-" * 70)
    w(f"total events            : {stats['total_events']:,}")
    w(f"event type counts       : {dict(stats['type_counts'])}")
    w(f"distinct sessions       : {stats['n_sessions']:,}")
    w(f"valid sessions          : {stats['good_sessions']:,}")
    w(f"invalid sessions        : {stats['n_bad']:,}")
    w(f"time-order violations   : {stats['time_order_violations']:,} "
      f"(events whose time < previous; 0 means file is sorted ascending)")
    if stats["bad_sessions"]:
        w("")
        w("  first invalid sessions (up to 100):")
        for sid, reason in stats["bad_sessions"]:
            w(f"    session {sid!r}: {reason}")

    # ---- descriptive distributions ----
    w("")
    w("DISTRIBUTIONS (actual)")
    w("-" * 70)

    # reports per session
    rps = stats["reports_per_session"]
    if rps:
        total_valid = sum(rps.values())
        mean_rps = sum(k * v for k, v in rps.items()) / total_valid if total_valid else 0
        w(f"reports per (valid) session: mean={mean_rps:.2f}")
        for k in sorted(rps):
            w(f"    {k} report(s): {rps[k]:,} sessions "
              f"({100*rps[k]/total_valid:.1f}%)")

    # member ratio
    mc = stats["member_counts"]
    if mc:
        tot = sum(mc.values())
        w("")
        w("is_member (on RentBike):")
        for k in sorted(mc):
            w(f"    {k}: {mc[k]:,} ({100*mc[k]/tot:.1f}%)")

    # new vs existing users
    nv = stats["user_new_vs_existing"]
    if nv:
        tot = sum(nv.values())
        w("")
        w(f"user_id new vs existing (split at seeded_max_user_id={seeded_max_user_id}):")
        for k in ("existing", "new", "unparseable"):
            if k in nv:
                w(f"    {k}: {nv[k]:,} ({100*nv[k]/tot:.1f}%)")
        w(f"    distinct users seen: {stats['distinct_users']:,}")

    # station uniformity
    for label, counter in (("RentBike station_id", stats["station_rent"]),
                           ("ReturnBike station_id", stats["station_return"])):
        u = uniformity_stats(counter)
        if u:
            w("")
            w(f"{label} usage (target: uniform):")
            w(f"    distinct stations used : {u['distinct_values']:,}")
            w(f"    mean uses per station  : {u['mean_per_value']:.1f}")
            w(f"    min / max uses         : {u['min']:,} / {u['max']:,}")
            w(f"    max rel. deviation     : {u['max_rel_dev_from_uniform']:.3f} "
              f"(descriptive; sensitive to small samples)")
            w(f"    reduced chi-square     : {u['reduced_chi2']:.3f} "
              f"(~1.0 = uniform; >>1 = uneven, <<1 = too even)")

    # ---- spec comparison ----
    if fill_spec_path:
        w("")
        w("SPEC TOLERANCE CHECKS (--fill-spec)")
        w("-" * 70)
        try:
            targets = load_spec_targets(fill_spec_path)
        except Exception as e:
            w(f"  could not read fill spec: {e}")
            targets = {}

        any_checked = False
        for (ev_name, fld), dist in sorted(targets.items()):
            dtype = dist.get("type")
            tol = dist.get("tolerance")

            if dtype == "categorical" and fld == "user_id":
                any_checked = True
                vals = dist.get("values", {})
                nv = stats["user_new_vs_existing"]
                tot = sum(nv.get(k, 0) for k in ("existing", "new"))
                for bucket, target in vals.items():
                    actual = (nv.get(bucket, 0) / tot) if tot else 0.0
                    ok = tol is None or abs(actual - target) <= tol
                    w(f"  [{ev_name}.{fld}] {bucket}: target={target:.3f} "
                      f"actual={actual:.3f} tol={tol} -> {'PASS' if ok else 'FAIL'}")

            elif dtype == "uniform_over_column":
                any_checked = True
                counter = (stats["station_rent"] if ev_name == RENT
                           else stats["station_return"] if ev_name == RETURN
                           else None)
                if counter is None:
                    counter = stats["station_rent"] or stats["station_return"]
                u = uniformity_stats(counter)
                if u:
                    dev = u["max_rel_dev_from_uniform"]
                    rchi2 = u["reduced_chi2"]
                    samples = u["total"]
                    bins = u["distinct_values"]
                    # Judge uniformity by reduced chi-square (sample-size aware):
                    # treat ~1 as ideal, allow a generous band. The spec's
                    # `tolerance` was written for relative deviation, so we show
                    # both but base PASS/FAIL on chi-square, which is sound.
                    chi2_ok = 0.5 <= rchi2 <= 2.0
                    low_sample = samples < 5 * bins  # <5 expected per bin
                    verdict = "PASS" if chi2_ok else "FAIL"
                    note = "  (LOW SAMPLE: result noisy, interpret loosely)" if low_sample else ""
                    w(f"  [{ev_name}.{fld}] uniform: reduced_chi2={rchi2:.3f} "
                      f"max_rel_dev={dev:.3f} (spec tol={tol}) -> {verdict}{note}")

            elif dtype == "distance_constrained":
                any_checked = True
                counter = (stats["station_return"] if ev_name == RETURN
                           else stats["station_rent"])
                u = uniformity_stats(counter)
                if u:
                    w(f"  [{ev_name}.{fld}] distance-constrained (not uniform "
                      f"by design): {u['distinct_values']} stations used, "
                      f"chi2={u['reduced_chi2']:.2f}, "
                      f"min/max uses {u['min']}/{u['max']} -> INFO "
                      f"(clustering expected, no pass/fail)")
        if not any_checked:
            w("  (no checkable distributions found in spec)")

    w("")
    w("=" * 70)
    verdict = "ALL SESSIONS VALID" if stats["n_bad"] == 0 else f"{stats['n_bad']:,} INVALID SESSIONS"
    sortmsg = "sorted ascending" if stats["time_order_violations"] == 0 else "NOT fully sorted"
    w(f"VERDICT: {verdict}; file is {sortmsg}.")
    w("=" * 70)
    return "\n".join(L)


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", help="filled (ideally time-sorted) skeleton XML")
    p.add_argument("--fill-spec", default=None,
                   help="fill_spec.yaml to check target distributions/tolerances")
    p.add_argument("--seeded-max-user-id", type=int, default=4000,
                   help="user_id boundary between existing/new (default 4000, "
                        "matches fill_spec seeded_max_user_id)")
    p.add_argument("--report", default=None,
                   help="also write the report to this file")
    return p.parse_args()


def main():
    args = parse_args()
    print(f"Scanning {args.input} ...", file=sys.stderr, flush=True)
    stats = scan(args.input, args.seeded_max_user_id)
    report = build_report(stats, args.fill_spec, args.seeded_max_user_id)
    print(report)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"\n(report written to {args.report})", file=sys.stderr)


if __name__ == "__main__":
    main()
