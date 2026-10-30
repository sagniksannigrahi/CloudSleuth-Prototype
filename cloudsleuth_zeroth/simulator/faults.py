"""How each of the 16 fault kinds changes the model state.

make_fault() picks a target and random strength for one case.
apply_fault() changes the State at one time step (only after the fault start).
"""

from ..topology import CALLS, DATABASE, DB_CALLERS, SERVICES
from .model import expected

# Which services each kind may hit.
HAS_CALLER = ["orders", "inventory", "payments"]            # someone calls them
HAS_CALLEE = [s for s in SERVICES if CALLS[s]]              # they call someone
SIMPLE_SERVICE_FAULTS = ["slow_service", "cpu_hog", "exception_burst"]


def make_fault(kind, rng, index):
    """Return a fault description: kind, target, strength, true root causes.

    `index` (0..7) rotates targets so every service gets used.
    """
    pick = lambda options: options[index % len(options)]  # noqa: E731
    if kind in ("db_lock", "db_slow_query"):
        caller = pick(["inventory", "payments", "orders", "worker"])
        return {"kind": kind, "target": DATABASE, "caller": caller,
                "strength": rng.uniform(800, 2500) if kind == "db_lock" else rng.uniform(20, 40),
                "root_causes": [DATABASE]}
    if kind == "multi_service":
        a, b = rng.sample(SERVICES[:4], 2)
        parts = [make_fault(rng.choice(SIMPLE_SERVICE_FAULTS), rng, 0) for _ in range(2)]
        parts[0].update(target=a, root_causes=[a])
        parts[1].update(target=b, root_causes=[b])
        return {"kind": kind, "parts": parts, "root_causes": [a, b]}
    if kind == "multi_db_and_service":
        db = make_fault("db_lock", rng, index)
        svc = make_fault(rng.choice(SIMPLE_SERVICE_FAULTS), rng, index)
        svc.update(target=pick(["gateway", "payments", "orders"]))
        svc["root_causes"] = [svc["target"]]
        return {"kind": kind, "parts": [db, svc], "root_causes": [DATABASE, svc["target"]]}

    if kind in ("bad_config",):
        target = pick(HAS_CALLEE)
    elif kind == "pool_misconfig":
        target = pick(DB_CALLERS)
    elif kind in ("service_crash", "service_down", "network_delay", "packet_loss"):
        target = pick(HAS_CALLER)
    else:
        target = pick(SERVICES)
    strength = {
        "slow_service": rng.uniform(300, 900),
        "latency_spikes": rng.uniform(500, 1500),
        "cpu_hog": rng.uniform(0.93, 0.99),
        "memory_leak": rng.uniform(4, 8),
        "exception_burst": rng.uniform(0.2, 0.5),
        "bad_deploy": rng.uniform(0.1, 0.35),
        "bad_config": rng.uniform(0.3, 0.6),
        "pool_misconfig": rng.uniform(150, 500),
        "network_delay": rng.uniform(150, 500),
        "packet_loss": rng.uniform(0.25, 0.4),
    }.get(kind, 0.0)
    return {"kind": kind, "target": target, "strength": strength, "root_causes": [target]}


def apply_fault(fault, st, k):
    """Change state `st` for step k (k = steps since the fault started)."""
    kind, s, x = fault["kind"], fault.get("target"), fault.get("strength", 0.0)
    if "parts" in fault:
        for part in fault["parts"]:
            apply_fault(part, st, k)
    elif kind == "db_lock":
        c = fault["caller"]
        st.db_ms[c] += x
        st.db_err[c] = 0.03                     # some statement timeouts
        st.db_stats["lock_waits"] += 4 + x / 250
        st.db_stats["active_connections"] += 8
        st.db_stats["mean_query_ms"] *= 3
    elif kind == "db_slow_query":
        c = fault["caller"]
        st.db_ms[c] *= x
        st.db_stats["mean_query_ms"] *= x / 3
        st.db_stats["db_cpu"] += 0.5
        st.db_stats["active_connections"] += 3
    elif kind == "slow_service":
        st.own_ms[s] += x
    elif kind == "latency_spikes":
        if k % 7 < 4:                            # 4 steps on, 3 steps off
            st.own_ms[s] += x
    elif kind == "cpu_hog":
        st.cpu[s] = x
        st.own_ms[s] *= 4
    elif kind == "memory_leak":
        st.mem_mb[s] += x * k
        st.own_ms[s] *= 1 + 0.02 * k
        if x * k > 200:
            st.err[s] = 0.05                     # out-of-memory errors later on
    elif kind == "exception_burst":
        st.err[s] = x
    elif kind == "bad_deploy":
        st.err[s] = x
        st.own_ms[s] *= 1.3
    elif kind == "bad_config":
        # The new timeout is shorter than the callee normally needs.
        fastest = min(expected(c, st)[0] for c in CALLS[s])
        st.timeout_ms[s] = x * fastest
    elif kind == "pool_misconfig":
        st.own_ms[s] += x                        # waiting for a free DB connection
        st.pool_wait.add(s)
        st.db_stats["active_connections"] -= 2
    elif kind == "service_crash":
        phase = k % 6                            # down 2 steps, up 4 steps
        st.down[s] = phase < 2
        if phase == 2:
            st.restarted.add(s)
    elif kind == "service_down":
        st.down[s] = True
    elif kind == "network_delay":
        st.net_ms[s] += x
    elif kind == "packet_loss":
        st.loss[s] = x


def change_events(fault, start_step, interval_s):
    """Deploy / config events that a real CI/CD or config system would log."""
    if "parts" in fault:
        return [e for p in fault["parts"] for e in change_events(p, start_step, interval_s)]
    t = start_step * interval_s - 3
    s = fault["target"]
    if fault["kind"] == "bad_deploy":
        return [{"t": t, "service": s, "kind": "deploy", "detail": f"{s} v1.4.2 -> v1.5.0"}]
    if fault["kind"] == "bad_config":
        return [{"t": t, "service": s, "kind": "config",
                 "detail": f"{s}: client timeout lowered from 2000 ms to a few ms"}]
    if fault["kind"] == "pool_misconfig":
        return [{"t": t, "service": s, "kind": "config", "detail": f"{s}: db pool size 20 -> 2"}]
    return []
