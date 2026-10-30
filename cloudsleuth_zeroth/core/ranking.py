"""Step 4: evidence-based ranking ("method D", rule-based).

For every candidate (each service, plus the database when DB evidence is on)
we collect pieces of EVIDENCE. Each piece either SUPPORTS or CONTRADICTS the
idea "this candidate is the root cause" and has a hand-set weight.

    raw score = sum(supporting weights) - sum(contradicting weights)

The raw score is NOT a probability and is NOT calibrated (calibration is
planned for later). The weights below are a first guess, written by hand.
"""

import math
from dataclasses import asdict, dataclass

# Weight of a persistent metric anomaly, per metric.
METRIC_WEIGHT = {
    "latency_p95_ms": 0.5, "error_rate": 0.5, "rps": 0.3, "cpu": 2.0, "memory_mb": 2.0,
    "missing_data": 1.5, "lock_waits": 3.0, "mean_query_ms": 2.0, "max_tx_duration_s": 2.0,
    "active_connections": 0.5, "db_cpu": 1.0,
}
DB_METRICS = {"lock_waits", "mean_query_ms", "max_tx_duration_s", "active_connections", "db_cpu"}


@dataclass
class Evidence:
    side: str        # "support" or "contradict"
    weight: float
    tag: str         # short machine name, used to guess the fault type
    text: str        # one plain-English sentence for the report


def _own_time_rise(attr):
    b, i = attr.get("own_ms_before"), attr.get("own_ms_incident")
    if b is None or i is None:
        return 0.0, b, i
    return i - b, b, i


def _is_own_rise(delta, before):
    return before is not None and delta > max(15.0, 0.5 * before)


def collect(node, view, anomalies, attr, attr_all):
    """All evidence for one candidate."""
    ev = []
    sup = lambda w, tag, text: ev.append(Evidence("support", round(w, 2), tag, text))      # noqa: E731
    con = lambda w, tag, text: ev.append(Evidence("contradict", round(w, 2), tag, text))   # noqa: E731
    iv = view["interval_s"]
    is_db = node == view["database"]

    # --- traces: own time, errors, network, reachability
    delta, b, i = _own_time_rise(attr)
    own_up = _is_own_rise(delta, b)
    if own_up:
        sup(min(4.0, 1 + math.log2(i / max(b, 1.0)) / 2), "own_time",
            f"{node}'s OWN work time per request rose from {b:.0f} ms to {i:.0f} ms")
    e = attr["errors_started_incident"] - attr["errors_started_before"]
    if e > 0.05:
        sup(2 + 2 * min(1.0, e * 2), "errors_here",
            f"errors START in {node} itself in {attr['errors_started_incident']:.0%} of requests "
            f"(before: {attr['errors_started_before']:.0%})")
    g = attr["gave_up_incident"] - attr["gave_up_before"]
    if g > 0.05:
        sup(3.0, "gave_up", f"{node}'s outgoing calls failed in {attr['gave_up_incident']:.0%} of requests "
            "although the called service answered fine (it gave up too early, e.g. a timeout)")
    gb, gi = attr.get("net_gap_ms_before"), attr.get("net_gap_ms_incident")
    if gb is not None and gi is not None and gi - gb > max(30.0, gb):
        irregular = (attr.get("net_gap_ms_median_incident") or 0) < 0.5 * gi
        sup(3.0, "net_gap_irregular" if irregular else "net_gap",
            f"network time on calls INTO {node} rose from {gb:.0f} ms to {gi:.0f} ms"
            + (" (only some calls: looks like packet loss / retries)" if irregular else ""))
    u = attr["unreachable_incident"] - attr["unreachable_before"]
    if u > 0.05:
        sup(4.0, "unreachable", f"{attr['unreachable_incident']:.0%} of calls into {node} got NO answer")

    # --- metrics (persistent anomalies only)
    for a in anomalies:
        w = METRIC_WEIGHT.get(a.metric, 0.5)
        if a.metric == "restarts":
            continue                            # counted below, from the logs
        if a.metric == "missing_data":
            sup(w, "missing_data", f"{node} stopped reporting metrics ({a.fraction:.0%} of readings "
                f"missing from t={a.onset * iv}s)")
        else:
            sup(w, f"metric:{a.metric}", f"{a.metric} unusual from t={a.onset * iv}s: normal "
                f"{a.baseline:g} -> up to {a.peak_value:g} (score {a.peak_z:g}, stayed unusual)")

    # --- logs and changes
    restarts = [e for e in view["incident_logs"] if e["service"] == node and "starting" in e["msg"]]
    if restarts:
        sup(2.0, "restart", f"{node} restarted {len(restarts)} time(s) during the incident (logs)")
    own_errs = lambda logs: sum(1 for e in logs if e["service"] == node and e["level"] == "ERROR"  # noqa: E731
                                and not e["msg"].startswith("call to"))
    if own_errs(view["incident_logs"]) >= 3 and own_errs(view["incident_logs"]) > 3 * own_errs(view["baseline_logs"]):
        sup(0.5, "error_logs", f"{own_errs(view['incident_logs'])} error logs from {node}'s own code")
    for c in view["recent_changes"]:
        if c["service"] == node:
            sup(1.5, f"change:{c['kind']}", f"recent {c['kind']} change at t={c['t']}s: {c['detail']}")

    # --- contradicting evidence
    has_latency = any(a.metric == "latency_p95_ms" for a in anomalies)
    wb, wi = attr.get("wait_ms_before"), attr.get("wait_ms_incident")
    if has_latency and not own_up and wb is not None and wi is not None and wi > 1.5 * wb + 10:
        con(1.5, "just_waiting", f"{node} is slow mostly because it is WAITING on others "
            f"(waiting {wb:.0f} -> {wi:.0f} ms); its own work did not grow")
    for callee in view["callees"].get(node, []):
        c_delta, c_b, _ = _own_time_rise(attr_all.get(callee, {}))
        if _is_own_rise(c_delta, c_b) and c_delta > max(delta, 0):
            con(1.0, "callee_worse", f"{callee}, which {node} calls, has a bigger own-time rise "
                f"(+{c_delta:.0f} ms vs +{max(delta, 0):.0f} ms)")
    if is_db and not any(a.metric in DB_METRICS for a in anomalies):
        con(2.0, "db_stats_normal", "database stats (locks, query time, connections) look normal")
    support_tags = {x.tag for x in ev if x.side == "support"}
    if not support_tags:
        con(1.0, "nothing_unusual", f"no unusual signal on {node}")
    elif all(t.startswith("change:") for t in support_tags):
        con(1.0, "change_only", f"{node} had a change but shows nothing unusual itself")
    return ev


def guess_fault_type(node, view, evidence):
    """Map the evidence of the top candidate to one of the 16 fault kinds."""
    tags = {e.tag for e in evidence if e.side == "support"}
    if node == view["database"]:
        return "db_lock" if "metric:lock_waits" in tags else "db_slow_query"
    if "restart" in tags:
        return "service_crash"
    if "unreachable" in tags or "missing_data" in tags:
        return "service_down"
    if "gave_up" in tags:
        return "bad_config"
    if "change:config" in tags and "own_time" in tags:
        return "pool_misconfig"
    if "change:config" in tags and "errors_here" in tags:
        return "bad_config"
    if "errors_here" in tags or {"error_logs", "metric:error_rate"} <= tags:
        return "bad_deploy" if "change:deploy" in tags else "exception_burst"
    # CPU / memory before network: a starved process also answers late, which
    # looks like network delay; a real network delay does not raise CPU.
    if "metric:memory_mb" in tags:
        return "memory_leak"
    if "metric:cpu" in tags:
        return "cpu_hog"
    if "net_gap" in tags or "net_gap_irregular" in tags:
        return "packet_loss" if "net_gap_irregular" in tags else "network_delay"
    if "own_time" in tags:
        lat = [e for e in evidence if e.tag == "metric:latency_p95_ms"]
        bursty = view.get("latency_fraction", {}).get(node, 1.0) < 0.75
        return "latency_spikes" if bursty and lat else "slow_service"
    return "unknown"


def rank(view, anomalies, attribution):
    """Return candidates sorted by raw score, each with its evidence."""
    by_node = {}
    for a in anomalies:
        by_node.setdefault(a.node, []).append(a)
    view = dict(view)
    view["latency_fraction"] = {a.node: a.fraction for a in anomalies if a.metric == "latency_p95_ms"}
    ranked = []
    for node in view["candidates"]:
        ev = collect(node, view, by_node.get(node, []), attribution[node], attribution)
        score = sum(e.weight for e in ev if e.side == "support") - sum(e.weight for e in ev if e.side == "contradict")
        ranked.append({"node": node, "raw_score": round(score, 2),
                       "support": [asdict(e) for e in ev if e.side == "support"],
                       "contradict": [asdict(e) for e in ev if e.side == "contradict"],
                       "_evidence": ev})
    ranked.sort(key=lambda r: (-r["raw_score"], r["node"]))
    top = ranked[0]
    fault_type = guess_fault_type(top["node"], view, top["_evidence"])
    for r in ranked:
        del r["_evidence"]
    return ranked, fault_type
