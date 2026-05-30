#!/usr/bin/env python3
"""Sort a filled skeleton event stream by increasing `time`.

Reads a (possibly huge) XML event stream and writes a new stream with the same
events ordered by ascending numeric `time`. Ties keep their original file order
(stable). Output is one event per line with no blank lines between events.

Memory stays bounded regardless of input size: events are written into sorted
temp "run" files (external merge sort), then k-way merged with a heap. Only one
sort buffer and one event per run file are ever in RAM.

Both skeleton layouts are supported and auto-detected:
  * flat:       <RentBike time="56">...</RentBike>
  * structured: <Event time="56"><Type>..</Type>...</Event>  (or a <Time> child,
                or an <Attribute name="time">)

Usage:
    python3 sort_by_time.py INPUT.xml [--out OUT.xml]
                            [--buffer 200000] [--tmpdir DIR] [--root-tag TAG]
"""
from __future__ import annotations

import argparse
import heapq
import json
import os
import tempfile
import xml.etree.ElementTree as ET


def get_time(elem):
    """Numeric time used for sorting. Reads the `time` attribute first, then a
    <Time> child, then an <Attribute name="time">. Events with no parseable
    time sort last (float inf) rather than being dropped."""
    t = elem.get("time")
    if t is None:
        child = elem.find("Time")
        if child is not None:
            t = child.text
        else:
            for a in elem.iter("Attribute"):
                if a.get("name") == "time":
                    t = a.text
                    break
    if t is None:
        return float("inf")
    try:
        return float(t)
    except (TypeError, ValueError):
        return float("inf")


def serialize(elem):
    """One-line serialization with no surrounding whitespace."""
    return ET.tostring(elem, encoding="unicode").strip()


def _flush_run(buf, tmpdir, runs):
    if not buf:
        return
    buf.sort(key=lambda r: (r[0], r[1]))  # (time, file_index): stable
    fd, path = tempfile.mkstemp(prefix="sortrun_", suffix=".jsonl", dir=tmpdir)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for time_val, idx, raw in buf:
            t = "Infinity" if time_val == float("inf") else time_val
            f.write(json.dumps([t, idx, raw]) + "\n")
    runs.append(path)
    buf.clear()


def _run_iter(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            t, idx, raw = json.loads(line)
            time_val = float("inf") if t == "Infinity" else t
            yield (time_val, idx, raw)


def sort_by_time(input_path, out_path, buffer_size, tmpdir, root_tag):
    out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="sortbytime_", dir=tmpdir)

    detected_root = root_tag
    depth = 0
    idx = 0
    buf = []
    runs = []

    print(f"[phase 1] reading + staging sorted runs from {input_path} ...",
          flush=True)
    context = ET.iterparse(input_path, events=("start", "end"))
    for ev, elem in context:
        if ev == "start":
            if depth == 0 and detected_root is None:
                detected_root = elem.tag
            depth += 1
            continue
        depth -= 1
        if depth != 1:
            continue  # root close (0) or inner element (>1)

        buf.append((get_time(elem), idx, serialize(elem)))
        idx += 1
        if len(buf) >= buffer_size:
            _flush_run(buf, work, runs)
        elem.clear()
        if idx % 200000 == 0:
            print(f"  ...staged {idx} events", flush=True)

    _flush_run(buf, work, runs)
    if detected_root is None:
        detected_root = "EventStream"
    print(f"[phase 1] done: {idx} events in {len(runs)} sorted runs.",
          flush=True)

    print(f"[phase 2] merging {len(runs)} runs ...", flush=True)
    iters = [_run_iter(p) for p in runs]
    merged = heapq.merge(*iters, key=lambda r: (r[0], r[1]))

    written = 0
    with open(out_path, "w", encoding="utf-8") as out:
        out.write('<?xml version="1.0" encoding="utf-8"?>\n')
        out.write(f"<{detected_root}>\n")
        for time_val, file_index, raw in merged:
            out.write(raw)
            out.write("\n")
            written += 1
            if written % 200000 == 0:
                print(f"  ...wrote {written} events", flush=True)
        out.write(f"</{detected_root}>\n")

    for p in runs:
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        os.rmdir(work)
    except OSError:
        pass

    print(f"[phase 2] done: wrote {written} events to {out_path}.", flush=True)
    return written


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", help="path to filled skeleton XML")
    p.add_argument("--out", default=None,
                   help="output path (default: INPUT_sorted.xml)")
    p.add_argument("--buffer", type=int, default=200000,
                   help="events per in-memory sort buffer (default 200000)")
    p.add_argument("--tmpdir", default=None,
                   help="dir for temp run files (needs ~input size free)")
    p.add_argument("--root-tag", default=None,
                   help="override stream root tag (auto-detected otherwise)")
    return p.parse_args()


def main():
    args = parse_args()
    base, ext = os.path.splitext(args.input)
    out = args.out or f"{base}_sorted{ext or '.xml'}"
    sort_by_time(args.input, out, args.buffer, args.tmpdir, args.root_tag)


if __name__ == "__main__":
    main()
