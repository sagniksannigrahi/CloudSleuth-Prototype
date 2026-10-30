"""Step 2: the telemetry snapshot.

prepare() turns a telemetry file into the view the diagnosis works on.
With use_db=False all database data is switched off:
  * database stats are dropped
  * the database is not a candidate cause
  * DB query spans are treated as plain work of the service that made them
    (this is what a tool that cannot see the database would do)

cut() splits the snapshot around the anomaly onset into a "before" part
(the normal reference period) and an "incident" part.
"""

CHANGE_LOOKBACK_S = 120   # changes up to 2 minutes before the onset count as "recent"


def prepare(telemetry, use_db=True):
    services = list(telemetry["services"])
    db_name = telemetry.get("database") or "postgres"
    metrics = {s: telemetry["metrics"].get(s, {}) for s in services}
    has_db = use_db and bool(telemetry.get("db"))
    if has_db:
        metrics[db_name] = telemetry["db"]

    traces = []
    for trace in telemetry.get("traces", []):
        spans = []
        for span in trace["spans"]:
            span = dict(span)
            if span["kind"] == "db" and not use_db:
                span["kind"], span["peer"] = "internal", None   # DB invisible
            spans.append(span)
        traces.append(spans)

    candidates = services + ([db_name] if use_db else [])
    callees = {}
    for a, b in telemetry.get("edges", []):
        if b in candidates:
            callees.setdefault(a, []).append(b)

    steps = telemetry.get("steps") or max(len(v) for m in metrics.values() for v in m.values())
    return {
        "case_id": telemetry["case_id"],
        "source": telemetry.get("source", "?"),
        "interval_s": telemetry["interval_s"],
        "steps": steps,
        "services": services,
        "database": db_name,
        "use_db": use_db,
        "candidates": candidates,
        "callees": callees,
        "metrics": metrics,
        "traces": traces,
        "logs": telemetry.get("logs", []),
        "changes": telemetry.get("changes", []),
    }


def trace_step(spans, interval_s):
    """Time step of a trace = start of its earliest span."""
    return int(min(s["start_ms"] for s in spans) / 1000 / interval_s)


def cut(view, baseline_end, onset):
    """Add before/incident windows of traces, logs and the recent changes."""
    iv = view["interval_s"]
    before_s, onset_s = baseline_end * iv, onset * iv
    view = dict(view)
    view["baseline_end"], view["onset"] = baseline_end, onset
    view["baseline_traces"] = [t for t in view["traces"] if t and trace_step(t, iv) < baseline_end]
    view["incident_traces"] = [t for t in view["traces"] if t and trace_step(t, iv) >= onset]
    view["baseline_logs"] = [e for e in view["logs"] if e["t"] < before_s]
    view["incident_logs"] = [e for e in view["logs"] if e["t"] >= onset_s]
    view["recent_changes"] = [c for c in view["changes"] if c["t"] >= onset_s - CHANGE_LOOKBACK_S]
    return view
