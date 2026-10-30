"""The small service graph used by BOTH datasets (simulator and demo app).

    gateway -> orders -> inventory
                      -> payments
                      -> (queue) -> worker
    orders, inventory, payments, worker -> postgres (database)
"""

SERVICES = ["gateway", "orders", "inventory", "payments", "worker"]
DATABASE = "postgres"

# Synchronous HTTP calls: caller -> list of callees.
CALLS = {
    "gateway": ["orders"],
    "orders": ["inventory", "payments"],
    "inventory": [],
    "payments": [],
    "worker": [],
}

# Services that talk to the database.
DB_CALLERS = ["orders", "inventory", "payments", "worker"]

# Every edge in the graph (used only for display).
EDGES = [
    ["gateway", "orders"],
    ["orders", "inventory"],
    ["orders", "payments"],
    ["orders", "worker"],  # through the job queue (async)
] + [[s, DATABASE] for s in DB_CALLERS]
