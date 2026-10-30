"""Recorder: save a telemetry snapshot of the live demo app for a time window.

Pulls, for [start, end]:
  * metrics every 5 s from Prometheus (service metrics + postgres-exporter DB stats)
  * traces from Jaeger (api/v3, OTLP JSON)
  * logs from Loki (config-change logs also become "changes")
and writes them in the SAME format as the simulator, so the diagnosis code
works on both datasets. Standard library only.
"""

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from cloudsleuth_zeroth.topology import DATABASE, EDGES, SERVICES

PROMETHEUS = "http://localhost:9090"
JAEGER = "http://localhost:16686"
LOKI = "http://localhost:3100"
STEP_S = 5

RATE = "20s"
SERVICE_QUERIES = {
    "latency_p95_ms": f"histogram_quantile(0.95, sum by (service, le) (rate(cs_request_duration_milliseconds_bucket[{RATE}])))",
    "error_rate": (f'(sum by (service) (rate(cs_requests_total{{status="error"}}[{RATE}])) '
                   f"or sum by (service) (rate(cs_requests_total[{RATE}])) * 0) "
                   f"/ sum by (service) (rate(cs_requests_total[{RATE}]))"),
    "rps": f"sum by (service) (rate(cs_requests_total[{RATE}]))",
    "cpu": "max by (service) (cs_process_cpu)",
    "memory_mb": "max by (service) (cs_process_memory_mb)",
}
DB_QUERIES = {
    "lock_waits": "max(pg_lock_waits_waiting)",
    "active_connections": 'sum(pg_stat_activity_count{state="active"})',
    "max_tx_duration_s": "max(pg_stat_activity_max_tx_duration)",
}


def _get(url, params):
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=30) as r:
        return r.read().decode()


# ---------------------------------------------------------------- metrics
def _prom_range(query, start, end):
    """{label value of 'service' (or '') : list of floats/None, one per 5 s step}."""
    data = json.loads(_get(f"{PROMETHEUS}/api/v1/query_range",
                           {"query": query, "start": start, "end": end, "step": STEP_S}))
    n = int((end - start) // STEP_S) + 1
    out = {}
    for series in data["data"]["result"]:
        values = [None] * n
        for ts, v in series["values"]:
            i = round((float(ts) - start) / STEP_S)
            if 0 <= i < n and v not in ("NaN", "+Inf", "-Inf"):
                values[i] = round(float(v), 4)
        out[series["metric"].get("service", "")] = values
    return out, n


def record_metrics(start, end):
    metrics = {s: {} for s in SERVICES}
    for name, query in SERVICE_QUERIES.items():
        result, n = _prom_range(query, start, end)
        for s in SERVICES:
            metrics[s][name] = result.get(s, [None] * n)
    db = {}
    for name, query in DB_QUERIES.items():
        result, n = _prom_range(query, start, end)
        db[name] = result.get("", [None] * n)
    return metrics, db, n


# ---------------------------------------------------------------- traces
def _attr(span, key):
    for a in span.get("attributes", []):
        if a["key"] == key:
            return next(iter(a["value"].values()))
    return None


def _jaeger_chunk(service, t_from, t_to, limit):
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")  # noqa: E731
    raw = _get(f"{JAEGER}/api/v3/traces", {"query.service_name": service, "query.start_time_min": iso(t_from),
                                           "query.start_time_max": iso(t_to), "query.num_traces": limit})
    spans, dec, i = [], json.JSONDecoder(), 0
    while i < len(raw):                       # the answer may be several JSON objects in a row
        while i < len(raw) and raw[i].isspace():
            i += 1
        if i >= len(raw):
            break
        obj, i = dec.raw_decode(raw, i)
        for rs in obj.get("result", {}).get("resourceSpans", []):
            svc = next(a["value"]["stringValue"] for a in rs["resource"]["attributes"] if a["key"] == "service.name")
            for ss in rs.get("scopeSpans", []):
                spans += [(svc, s) for s in ss.get("spans", [])]
    return spans


def record_traces(start, end):
    """Sample traces evenly over the window (Jaeger returns at most `limit` per query)."""
    raw, t = {}, start
    while t < end:
        for service, limit in (("gateway", 8), ("worker", 3)):
            try:
                for svc, s in _jaeger_chunk(service, t, min(t + 20, end), limit):
                    raw[(s["traceId"], s["spanId"])] = (svc, s)
            except Exception:
                pass                          # no traces in this chunk
        t += 20
    by_id = {sid: s for (_, sid), (_, s) in raw.items()}
    children_service = {}
    for (_, sid), (svc, s) in raw.items():
        if s.get("parentSpanId"):
            children_service[s["parentSpanId"]] = svc
    traces = {}
    for (tid, sid), (svc, s) in raw.items():
        kind_no = {"SPAN_KIND_INTERNAL": 1, "SPAN_KIND_SERVER": 2, "SPAN_KIND_CLIENT": 3,
                   "SPAN_KIND_PRODUCER": 4, "SPAN_KIND_CONSUMER": 5}.get(s.get("kind"), s.get("kind"))
        peer = None
        if _attr(s, "db.system"):
            kind, peer = "db", DATABASE
        elif kind_no in (3, 4):
            kind = "client"
            url = _attr(s, "url.full") or _attr(s, "http.url") or ""
            peer = _attr(s, "server.address") or urllib.parse.urlparse(url).hostname or children_service.get(sid)
        elif kind_no in (2, 5):
            kind = "server"
        else:
            kind = "internal"
        status = s.get("status", {}).get("code")
        parent = s.get("parentSpanId") or None
        traces.setdefault(tid, []).append({
            "trace_id": tid, "span_id": sid,
            "parent_id": parent if parent in by_id else None,
            "service": svc, "kind": kind, "name": s["name"], "peer": peer,
            "start_ms": round(int(s["startTimeUnixNano"]) / 1e6 - start * 1000, 2),
            "duration_ms": round((int(s["endTimeUnixNano"]) - int(s["startTimeUnixNano"])) / 1e6, 2),
            "error": status in (2, "STATUS_CODE_ERROR"),
        })
    return [{"trace_id": tid, "spans": spans} for tid, spans in traces.items()]


# ---------------------------------------------------------------- logs
def record_logs(start, end):
    logs, changes = [], []
    data = json.loads(_get(f"{LOKI}/loki/api/v1/query_range", {
        "query": '{service_name=~".+"}', "start": int(start * 1e9), "end": int(end * 1e9),
        "limit": 5000, "direction": "forward"}))
    for stream in data["data"]["result"]:
        labels = stream["stream"]
        service = labels.get("service_name")
        level = {"WARNING": "WARN"}.get(labels.get("severity_text", "INFO"), labels.get("severity_text", "INFO"))
        for ts, msg in stream["values"]:
            t = round(int(ts) / 1e9 - start, 1)
            logs.append({"t": t, "service": service, "level": level, "msg": msg})
            if msg.startswith("CHANGE "):
                changes.append({"t": t, "service": service, "kind": "config", "detail": msg[len("CHANGE "):]})
    return sorted(logs, key=lambda e: e["t"]), changes


def record(case_id, start, end):
    """Build one telemetry snapshot (dict) for the window [start, end] (unix seconds)."""
    start, end = int(start), int(end)
    metrics, db, steps = record_metrics(start, end)
    logs, changes = record_logs(start, end)
    return {
        "case_id": case_id, "source": "demo_app", "interval_s": STEP_S, "steps": steps,
        "window_start_unix": start,
        "services": SERVICES, "database": DATABASE, "edges": EDGES,
        "metrics": metrics, "db": db,
        "traces": record_traces(start, end),
        "logs": logs, "changes": changes,
    }
