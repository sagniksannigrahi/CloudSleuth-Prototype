"""Catalogue of the 16 fault kinds, in 8 groups.

The diagnosis core only uses these NAMES to describe its guess of the fault
type. It never learns which fault was injected into a case.
"""

FAULT_KINDS = {
    # kind              group           what it means
    "db_lock":          ("database",     "a transaction holds a table lock; queries wait"),
    "db_slow_query":    ("database",     "a query became slow (e.g. missing index)"),
    "slow_service":     ("delay",        "a service's own code became slow"),
    "latency_spikes":   ("delay",        "a service is slow in bursts (on/off)"),
    "cpu_hog":          ("resources",    "something burns CPU inside a service"),
    "memory_leak":      ("resources",    "memory keeps growing inside a service"),
    "exception_burst":  ("errors",       "a service starts throwing exceptions"),
    "bad_deploy":       ("errors",       "a new version was deployed and it throws errors"),
    "bad_config":       ("settings",     "a config change set a too-short timeout"),
    "pool_misconfig":   ("settings",     "a config change shrank the DB connection pool"),
    "service_crash":    ("availability", "a service keeps crashing and restarting"),
    "service_down":     ("availability", "a service is down and unreachable"),
    "network_delay":    ("network",      "extra network delay on calls into a service"),
    "packet_loss":      ("network",      "packet loss on calls into a service (retries)"),
    "multi_service":    ("multiple",     "two different services fail at the same time"),
    "multi_db_and_service": ("multiple", "a database fault plus a service fault together"),
}

GROUPS = sorted({g for g, _ in FAULT_KINDS.values()})


def group_of(kind):
    """Return the group of a fault kind ('normal' / 'unknown' map to themselves)."""
    return FAULT_KINDS[kind][0] if kind in FAULT_KINDS else kind
