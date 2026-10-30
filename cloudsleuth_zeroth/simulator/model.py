"""A tiny model of the service graph, step by step.

For every 5-second step we keep a `State`: how much own work each service
does, how slow its DB queries are, extra network delay, error chances, and so
on. Faults (faults.py) change the state. From the state we then produce
metrics, traces and logs (generate.py).
"""

import copy
import random
from dataclasses import dataclass, field

from ..topology import CALLS, DB_CALLERS, SERVICES

# Normal own-work time per request (ms) and normal DB query time (ms).
BASE_OWN_MS = {"gateway": 6, "orders": 14, "inventory": 9, "payments": 18, "worker": 22}
BASE_DB_MS = {"orders": 4, "inventory": 7, "payments": 5, "worker": 4}


@dataclass
class State:
    own_ms: dict            # service -> own work time per request
    db_ms: dict             # caller -> DB time per request
    net_ms: dict            # service -> network delay on calls INTO it
    err: dict               # service -> chance its own code fails
    db_err: dict            # caller -> chance its DB query fails
    loss: dict              # service -> chance a call into it needs a retransmit
    down: dict              # service -> True if not running at this step
    timeout_ms: dict        # caller -> client timeout on calls it makes
    cpu: dict               # service -> CPU use (0..1)
    mem_mb: dict            # service -> memory in MB
    rps: float              # requests per second entering the gateway
    db_stats: dict          # lock_waits, active_connections, mean_query_ms, db_cpu
    restarted: set = field(default_factory=set)   # services that restarted this step
    pool_wait: set = field(default_factory=set)   # services waiting for DB pool

    def copy(self):
        return copy.deepcopy(self)


def base_state(rng: random.Random) -> State:
    """Normal state; each case gets slightly different base values."""
    vary = lambda v: v * rng.uniform(0.8, 1.2)  # noqa: E731
    return State(
        own_ms={s: vary(BASE_OWN_MS[s]) for s in SERVICES},
        db_ms={s: vary(BASE_DB_MS[s]) for s in DB_CALLERS},
        net_ms={s: vary(1.0) for s in SERVICES},
        err={s: 0.002 for s in SERVICES},
        db_err={s: 0.0 for s in DB_CALLERS},
        loss={s: 0.0 for s in SERVICES},
        down={s: False for s in SERVICES},
        timeout_ms={s: 2000.0 for s in SERVICES},
        cpu={s: vary(0.25) for s in SERVICES},
        mem_mb={s: vary(180) for s in SERVICES},
        rps=vary(20),
        db_stats={"lock_waits": 0.2, "active_connections": vary(8),
                  "mean_query_ms": vary(3), "db_cpu": vary(0.2)},
    )


def expected(service, st: State):
    """Expected (latency_ms, error_chance) of one request to `service`."""
    lat = st.own_ms[service] + st.db_ms.get(service, 0.0)
    ok = (1 - st.err[service]) * (1 - st.db_err.get(service, 0.0))
    for child in CALLS[service]:
        if st.down[child]:
            lat += 2
            ok *= 0.0
            continue
        c_lat, c_err = expected(child, st)
        call = c_lat + st.net_ms[child] + st.loss[child] * 600
        if call > st.timeout_ms[service]:
            call, c_err = st.timeout_ms[service], 1.0
        lat += call
        ok *= (1 - c_err) * (1 - st.loss[child] * 0.25)
    return lat, 1 - ok
