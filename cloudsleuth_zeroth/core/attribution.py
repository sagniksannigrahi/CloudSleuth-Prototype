"""Step 3: trace attribution: OWN time vs time WAITING on others.

For every span:  own time = span duration - time covered by its child spans.
  * server / internal span -> own time of that service
  * DB span                -> own time of the database (when DB evidence is on)
  * client span            -> its own time is the NETWORK gap between the
                              caller sending and the callee answering, so it is
                              charged to the network on calls INTO the callee

Error origin: a failing span whose children did not fail is where the error
started. Special cases for client spans:
  * failed with no answer at all          -> callee unreachable
  * failed although the callee answered OK -> caller gave up (e.g. timeout)
"""

from statistics import mean, median


def _covered_ms(span, children):
    """Length of the part of `span` covered by its children (merging overlaps)."""
    lo, hi = span["start_ms"], span["start_ms"] + span["duration_ms"]
    parts = sorted((max(lo, c["start_ms"]), min(hi, c["start_ms"] + c["duration_ms"])) for c in children)
    total, cur_start, cur_end = 0.0, None, None
    for a, b in parts:
        if b <= a:
            continue
        if cur_end is None or a > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = a, b
        else:
            cur_end = max(cur_end, b)
    if cur_end is not None:
        total += cur_end - cur_start
    return total


def one_trace(spans, database):
    """Per-node totals for a single trace."""
    kids = {}
    for s in spans:
        kids.setdefault(s["parent_id"], []).append(s)
    out = {}

    def add(node, key, value):
        out.setdefault(node, {}).setdefault(key, 0.0)
        out[node][key] += value

    for s in spans:
        children = kids.get(s["span_id"], [])
        own = max(0.0, s["duration_ms"] - _covered_ms(s, children))
        child_failed = any(c["error"] for c in children)
        if s["kind"] in ("server", "internal"):
            add(s["service"], "own_ms", own)
            others = [c for c in children if c["kind"] in ("client", "db")]
            add(s["service"], "wait_ms", _covered_ms(s, others))
            if s["error"] and not child_failed:
                add(s["service"], "errors_started", 1)
        elif s["kind"] == "db":
            add(database, "own_ms", own)
            if s["error"]:
                add(database, "errors_started", 1)
        elif s["kind"] == "client":
            callee = s["peer"]
            if children:
                add(callee, "net_gap_ms", own)
                if s["error"] and not child_failed:
                    add(s["service"], "gave_up", 1)          # callee was fine
            elif s["error"]:
                add(callee, "unreachable", 1)
            add(callee, "calls_in", 1)
    return out


def _summary(per_trace, node, key, how=mean):
    vals = [t[node].get(key, 0.0) for t in per_trace if node in t]
    return round(how(vals), 2) if vals else None


def attribute(view):
    """Compare before vs incident for every node. Returns {node: numbers}."""
    db = view["database"]
    before = [one_trace(t, db) for t in view["baseline_traces"]]
    during = [one_trace(t, db) for t in view["incident_traces"]]
    result = {}
    for node in view["candidates"]:
        r = {}
        for tag, traces in (("before", before), ("incident", during)):
            seen = [t for t in traces if node in t]
            calls = sum(t[node].get("calls_in", 0) for t in seen)
            r[f"own_ms_{tag}"] = _summary(traces, node, "own_ms")
            r[f"own_ms_median_{tag}"] = _summary(traces, node, "own_ms", median)
            r[f"wait_ms_{tag}"] = _summary(traces, node, "wait_ms")
            r[f"net_gap_ms_{tag}"] = _summary(traces, node, "net_gap_ms") if calls else None
            r[f"net_gap_ms_median_{tag}"] = _summary(traces, node, "net_gap_ms", median) if calls else None
            r[f"errors_started_{tag}"] = round(sum(t[node].get("errors_started", 0) for t in seen) / max(1, len(traces)), 3)
            r[f"gave_up_{tag}"] = round(sum(t[node].get("gave_up", 0) for t in seen) / max(1, len(traces)), 3)
            r[f"unreachable_{tag}"] = round(sum(t[node].get("unreachable", 0) for t in seen) / max(1, calls), 3)
        r["traces_before"], r["traces_incident"] = len(before), len(during)
        result[node] = r
    return result
