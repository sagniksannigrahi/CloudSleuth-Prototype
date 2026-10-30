"""Simulator (dataset 1): generate microservice failure cases on demand.

Each case is 72 steps x 5 s = 6 minutes of telemetry:
metrics, traces, logs, recent changes (deploy/config) and database stats.
The fault (if any) starts somewhere between minute 2:10 and 3:00.

Default dataset: 16 fault kinds x 8 cases = 128 fault cases + 16 normal = 144.
2 of the 8 cases per kind are MILD (weaker fault). Noise everywhere: jitter,
one-off spikes, missing points, scrape gaps, lost traces, unrelated changes.
Telemetry goes to  <out>/telemetry/,  true answers to  <out>/labels/  (hashed).

Run:  python -m cloudsleuth_zeroth.simulator.generate --out data/simulator
"""

import argparse
import random
from pathlib import Path

from .. import case_io, labels
from ..faults import FAULT_KINDS, group_of
from ..topology import CALLS, DATABASE, DB_CALLERS, EDGES, SERVICES
from .faults import apply_fault, change_events, make_fault
from .model import base_state, expected

STEPS = 72
INTERVAL_S = 5
SERVICE_METRICS = ["latency_p95_ms", "error_rate", "rps", "cpu", "memory_mb"]
DB_METRICS = ["lock_waits", "active_connections", "mean_query_ms", "db_cpu"]


# ---------------------------------------------------------------- traces
class TraceBuilder:
    """Builds one trace as a flat list of spans (like OpenTelemetry would)."""

    def __init__(self, rng, trace_id):
        self.rng, self.trace_id, self.spans, self.logs = rng, trace_id, [], []

    def _jit(self, ms):
        return ms * self.rng.lognormvariate(0, 0.25)

    def _add(self, service, kind, name, parent, start, duration, error, peer=None):
        span = {"trace_id": self.trace_id, "span_id": f"{self.trace_id}.{len(self.spans)}",
                "parent_id": parent, "service": service, "kind": kind, "name": name,
                "peer": peer, "start_ms": round(start, 2), "duration_ms": round(duration, 2),
                "error": error}
        self.spans.append(span)
        return span

    def server(self, s, start, st, parent=None, name="handle request"):
        """A request handled by service s; calls its DB and its callees."""
        span = self._add(s, "server", name, parent, start, 0, False)
        own = self._jit(st.own_ms[s])
        cursor = start + own / 2
        error = self.rng.random() < st.err[s]
        if error:
            self.logs.append(("ERROR", s, "unhandled exception in request handler"))
        if s in DB_CALLERS:
            db_err = self.rng.random() < st.db_err[s]
            dur = self._jit(st.db_ms[s])
            self._add(s, "db", "SQL query", span["span_id"], cursor, dur, db_err, peer=DATABASE)
            if db_err:
                self.logs.append(("ERROR", s, "database error: canceling statement due to statement timeout"))
            error |= db_err
            cursor += dur
        for child in CALLS[s]:
            dur, call_err = self._call(s, child, cursor, st, span)
            cursor += dur
            error |= call_err
        cursor += own / 2
        span["duration_ms"], span["error"] = round(cursor - start, 2), error
        return span

    def _call(self, s, child, start, st, parent):
        """Client span from s to child (and the child's own server span)."""
        client = self._add(s, "client", f"call {child}", parent["span_id"], start, 0, False, peer=child)
        if st.down[child]:
            dur, err, reason = self._jit(2), True, "connection refused"
        else:
            net = self._jit(st.net_ms[child])
            if self.rng.random() < st.loss[child]:
                net += self.rng.uniform(200, 1000)          # lost packet -> retransmit
            server = self.server(child, start + net / 2, st, client["span_id"])
            dur, err, reason = server["duration_ms"] + net, server["error"], "upstream returned 500"
            if dur > st.timeout_ms[s]:
                dur, err, reason = st.timeout_ms[s], True, f"timed out after {st.timeout_ms[s]:.0f} ms"
        if err:
            self.logs.append(("ERROR", s, f"call to {child} failed: {reason}"))
        client["duration_ms"], client["error"] = round(dur, 2), err
        return dur, err


def build_traces(rng, st, step, trace_no):
    """One checkout trace (and every 2nd step one worker trace) for this step."""
    out, logs = [], []
    t0 = step * INTERVAL_S * 1000 + rng.uniform(0, 4000)
    jobs = [("gateway", "POST /checkout")] + ([("worker", "process job")] if step % 2 == 0 else [])
    for i, (root, name) in enumerate(jobs):
        tb = TraceBuilder(rng, f"t{trace_no}-{i}")
        tb.server(root, t0, st, name=name)
        logs += tb.logs
        if rng.random() > 0.08:                     # missing data: 8% of traces lost
            out.append({"trace_id": tb.trace_id, "spans": tb.spans})
    return out, logs


# ---------------------------------------------------------------- metrics
def reachable(s, st):
    """A service gets traffic only if everything in front of it is up."""
    path = {"gateway": [], "orders": ["gateway"], "inventory": ["gateway", "orders"],
            "payments": ["gateway", "orders"], "worker": ["gateway", "orders"]}[s]
    return not any(st.down[p] for p in path)


def step_metrics(rng, st):
    m = {}
    for s in SERVICES:
        if st.down[s]:
            m[s] = {k: None for k in SERVICE_METRICS}
            continue
        lat, err = expected(s, st)
        rps = st.rps * rng.gauss(1, 0.05) if reachable(s, st) else 0.0
        m[s] = {
            "latency_p95_ms": lat * 1.5 * rng.gauss(1, 0.08),
            "error_rate": min(1.0, max(0.0, err + rng.gauss(0, 0.003))),
            "rps": rps,
            "cpu": min(1.0, max(0.0, st.cpu[s] * (0.6 + 0.4 * rps / st.rps) + rng.gauss(0, 0.02))),
            "memory_mb": st.mem_mb[s] + rng.gauss(0, 2),
        }
    d = st.db_stats
    db = {"lock_waits": max(0.0, round(rng.gauss(d["lock_waits"], 0.4))),
          "active_connections": max(0.0, rng.gauss(d["active_connections"], 0.8)),
          "mean_query_ms": d["mean_query_ms"] * rng.gauss(1, 0.08),
          "db_cpu": min(1.0, max(0.0, d["db_cpu"] + rng.gauss(0, 0.02)))}
    return m, db


def add_noise(rng, series, kind):
    """Missing points, single-point spikes, and sometimes a scrape gap."""
    for i, v in enumerate(series):
        if v is None:
            continue
        r = rng.random()
        if r < 0.03:
            series[i] = None                                   # missing point
        elif r < 0.05 and kind in ("latency_p95_ms", "mean_query_ms"):
            series[i] = v * 3                                  # one-off spike
        elif r < 0.05 and kind == "error_rate":
            series[i] = min(1.0, v + 0.1)


# ---------------------------------------------------------------- one case
def simulate_case(case_id, kind, rng, index):
    """Return (telemetry, label) for one case. kind=None means a normal case."""
    st0 = base_state(rng)
    start = rng.randint(26, 36)
    mild = bool(kind) and index % 4 == 3            # 2 of every 8 cases per kind
    fault = make_fault(kind, rng, index, mild) if kind else None
    metrics = {s: {k: [] for k in SERVICE_METRICS} for s in SERVICES}
    db = {k: [] for k in DB_METRICS}
    traces, logs = [], []
    mem_base = dict(st0.mem_mb)
    for step in range(STEPS):
        st = st0.copy()
        if fault and step >= start:
            apply_fault(fault, st, step - start)
        m, d = step_metrics(rng, st)
        for s in SERVICES:
            for k in SERVICE_METRICS:
                metrics[s][k].append(m[s][k])
        for k in DB_METRICS:
            db[k].append(d[k])
        new_traces, new_logs = build_traces(rng, st, step, step)
        traces += new_traces
        t = step * INTERVAL_S
        logs += [{"t": t, "service": s, "level": lvl, "msg": msg} for lvl, s, msg in new_logs]
        for s in st.restarted:
            logs.append({"t": t, "service": s, "level": "INFO", "msg": "service starting"})
        for s in st.pool_wait:
            logs.append({"t": t, "service": s, "level": "WARN", "msg": "waiting for a free database connection"})
        for s in SERVICES:
            if st.mem_mb[s] - mem_base[s] > 200:
                logs.append({"t": t, "service": s, "level": "WARN", "msg": "high memory usage"})
        if rng.random() < 0.3:                                  # background chatter
            logs.append({"t": t, "service": rng.choice(SERVICES), "level": "INFO", "msg": "request handled"})
        if rng.random() < 0.03:
            logs.append({"t": t, "service": rng.choice(SERVICES), "level": "WARN", "msg": "retrying cache refresh"})

    for s in SERVICES:
        for k in SERVICE_METRICS:
            add_noise(rng, metrics[s][k], k)
    for k in DB_METRICS:
        add_noise(rng, db[k], k)
    if rng.random() < 0.25:                                     # a scrape gap
        s, k, at = rng.choice(SERVICES), rng.choice(SERVICE_METRICS), rng.randint(5, 60)
        for i in range(at, at + rng.randint(4, 8)):
            metrics[s][k][i] = None

    changes = change_events(fault, start, INTERVAL_S) if fault else []
    if rng.random() < 0.3:                                      # an unrelated change (red herring)
        s = rng.choice(SERVICES)
        changes.append({"t": rng.randint(10, 60) * INTERVAL_S, "service": s,
                        "kind": rng.choice(["deploy", "config"]), "detail": f"{s}: routine update"})

    round_all = lambda xs: [None if v is None else round(v, 4) for v in xs]  # noqa: E731
    telemetry = {
        "case_id": case_id, "source": "simulator", "interval_s": INTERVAL_S, "steps": STEPS,
        "services": SERVICES, "database": DATABASE, "edges": EDGES,
        "metrics": {s: {k: round_all(v) for k, v in ms.items()} for s, ms in metrics.items()},
        "db": {k: round_all(v) for k, v in db.items()},
        "traces": traces,
        "logs": sorted(logs, key=lambda e: e["t"]),
        "changes": sorted(changes, key=lambda e: e["t"]),
    }
    label = {
        "case_id": case_id, "dataset": "simulator",
        "fault_kind": kind or "normal", "fault_group": group_of(kind) if kind else "normal",
        "root_causes": fault["root_causes"] if fault else [],
        "severity": ("mild" if mild else "strong") if fault else None,
        "fault_start_s": start * INTERVAL_S if fault else None,
        "details": fault,
    }
    return telemetry, label


def generate(out_dir, cases_per_kind=8, normal_cases=16, seed=42):
    """Generate the whole dataset. Returns the number of cases written."""
    out = Path(out_dir)
    for sub in ("telemetry", "labels"):                          # start clean
        for f in (out / sub).glob("*"):
            f.unlink()
    rng = random.Random(seed)
    plan = [(k, i) for k in FAULT_KINDS for i in range(cases_per_kind)]
    plan += [(None, i) for i in range(normal_cases)]
    rng.shuffle(plan)                       # case ids do not reveal the fault
    for n, (kind, i) in enumerate(plan, start=1):
        case_id = f"sim-{n:03d}"
        telemetry, label = simulate_case(case_id, kind, random.Random(f"{seed}-{n}"), i)
        case_io.save_telemetry(out, telemetry)
        labels.write_label(out, label)
    return len(plan)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/simulator")
    ap.add_argument("--cases-per-kind", type=int, default=8)
    ap.add_argument("--normal", type=int, default=16)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    n = generate(a.out, a.cases_per_kind, a.normal, a.seed)
    faulty = n - a.normal
    print(f"Simulator: wrote {n} cases ({faulty} with a fault, {a.normal} normal) "
          f"covering {len(FAULT_KINDS)} fault kinds")
    print(f"  telemetry -> {a.out}/telemetry/   labels (SHA-256 hashed) -> {a.out}/labels/")


if __name__ == "__main__":
    main()
