"""Fault lab: break the live demo app ON PURPOSE and write down exactly what was broken.

  python -m faultlab.fault_lab list
  python -m faultlab.fault_lab inject db_lock --duration 120

What `inject` does:
  1. checks the app is up and has ~2 minutes of normal traffic
  2. injects the fault and keeps it on for --duration seconds
  3. removes the fault
  4. records a telemetry snapshot (2 min before + the fault period)
     -> data/demo_app/telemetry/<case>.json
  5. writes the TRUE ANSWER separately, with its SHA-256 hash
     -> data/demo_app/labels/<case>.json  (+ labels/SHA256SUMS)
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from cloudsleuth_zeroth import case_io, labels
from cloudsleuth_zeroth.faults import FAULT_KINDS, group_of

from . import recorder

LIVE_DATASET = "data/demo_app"
COMPOSE = ["docker", "compose", "-f", "demo_app/docker-compose.yml"]
PORTS = {"gateway": 18080, "orders": 18081, "inventory": 18082, "payments": 18083, "worker": 18084}
BASELINE_S = 120
STATE_FILE = Path("faultlab/.state/last_fault_end")   # when the previous fault ended


# ---------------------------------------------------------------- helpers
def post(service, path, body):
    req = urllib.request.Request(f"http://localhost:{PORTS[service]}{path}", data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read() or b"{}")


def healthy(service):
    try:
        with urllib.request.urlopen(f"http://localhost:{PORTS[service]}/health", timeout=2):
            return True
    except Exception:
        return False


def compose_exec(service, *cmd, background=False):
    args = COMPOSE + ["exec", "-T", service, *cmd]
    if background:
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return subprocess.run(args, check=True, capture_output=True, text=True)


def psql(sql, background=False):
    return compose_exec("postgres", "psql", "-U", "cloudsleuth", "-d", "shop", "-c", sql, background=background)


TC_DELAY = ("tc qdisc add dev eth0 root handle 1: prio bands 4 priomap 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 && "
            "tc qdisc add dev eth0 parent 1:4 handle 40: netem delay 300ms 50ms && "
            "tc filter add dev eth0 protocol ip parent 1:0 prio 1 u32 match ip sport 8000 0xffff flowid 1:4")


# ---------------------------------------------------------------- live faults
# Each fault: target (the true root cause), what we do, how to start and stop it.
LIVE_FAULTS = {
    "db_lock": {
        "target": "postgres",
        "what": "a transaction holds an ACCESS EXCLUSIVE lock on the inventory table "
                "(the inventory service's queries wait on it)",
        "start": lambda d: psql(f"BEGIN; LOCK TABLE inventory IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep({d + 30}); COMMIT;",
                                background=True),
        "stop": lambda: psql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                             "WHERE query LIKE '%LOCK TABLE inventory%' AND pid <> pg_backend_pid();"),
    },
    "slow_service": {
        "target": "payments",
        "what": "payments' own code sleeps 600 ms per request",
        "start": lambda d: post("payments", "/admin/fault", {"slow_ms": 600}),
        "stop": lambda: post("payments", "/admin/reset", {}),
    },
    "service_crash": {
        "target": "payments",
        "what": "payments crashes (process exits) every ~20 s and Docker restarts it",
        "start": lambda d: post("payments", "/admin/fault", {"crash": True}),
        "repeat_every_s": 20,
        "stop": lambda: None,
    },
    "cpu_hog": {
        "target": "inventory",
        "what": "two busy threads burn CPU inside inventory",
        "start": lambda d: post("inventory", "/admin/fault", {"cpu_hog": True}),
        "stop": lambda: post("inventory", "/admin/reset", {}),
    },
    "bad_config": {
        "target": "orders",
        "what": "config change on orders: payments_timeout_s 2.0 -> 0.002 (2 ms, too short)",
        "start": lambda d: post("orders", "/admin/config", {"payments_timeout_s": 0.002}),
        "stop": lambda: post("orders", "/admin/config", {"payments_timeout_s": 2.0}),
    },
    "network_delay": {
        "target": "inventory",
        "what": "tc netem adds 300 ms (+-50 ms) delay to every response leaving inventory",
        "start": lambda d: compose_exec("inventory", "sh", "-c", TC_DELAY),
        "stop": lambda: compose_exec("inventory", "tc", "qdisc", "del", "dev", "eth0", "root"),
    },
    "normal": {
        "target": None,
        "what": "nothing is broken (a normal snapshot, to check for false alarms)",
        "start": lambda d: None,
        "stop": lambda: None,
    },
}

# TODO (planned): live versions of the other 10 fault kinds. They exist in the
# simulator already; the live injections are not written yet.
TODO_FAULTS = [k for k in FAULT_KINDS if k not in LIVE_FAULTS]


# ---------------------------------------------------------------- main steps
def check_ready():
    if not all(healthy(s) for s in PORTS):
        sys.exit("The demo app is not up. Run `make up` first (and wait ~2 minutes).")
    since = time.time() - BASELINE_S
    q = urllib.parse.urlencode({"query": 'cs_requests_total{service="gateway"}', "time": since})
    with urllib.request.urlopen(f"{recorder.PROMETHEUS}/api/v1/query?{q}", timeout=5) as r:
        ok = bool(json.loads(r.read())["data"]["result"])
    if not ok:
        print(f"[fault lab] need {BASELINE_S} s of normal traffic first; waiting ...", flush=True)
        time.sleep(BASELINE_S)
    # The 2 minutes before a fault are its "normal" reference, so they must not
    # contain the previous fault.
    if STATE_FILE.exists():
        wait = float(STATE_FILE.read_text()) + BASELINE_S + 15 - time.time()
        if wait > 0:
            print(f"[fault lab] waiting {wait:.0f} s so the previous fault is out of the reference window ...",
                  flush=True)
            time.sleep(wait)
    for s in PORTS:                                   # make sure nothing is left over
        post(s, "/admin/reset", {})


def inject(name, duration):
    fault = LIVE_FAULTS[name]
    check_ready()
    case_id = "live-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    t0 = time.time()
    print(f"[fault lab] {datetime.now():%H:%M:%S} injecting '{name}': {fault['what']}", flush=True)
    fault["start"](duration)
    try:
        last = t0
        while time.time() - t0 < duration:
            time.sleep(1)
            left = duration - (time.time() - t0)
            if int(left) % 15 == 0 and left >= 1:
                print(f"[fault lab]   fault active, {left:.0f} s left", flush=True)
            every = fault.get("repeat_every_s")
            if every and time.time() - last >= every and left > 5:
                target = fault["target"]
                for _ in range(20):                    # wait until it is back up
                    if healthy(target):
                        break
                    time.sleep(1)
                fault["start"](duration)
                last = time.time()
    finally:
        t_end = time.time()
        fault["stop"]()
        STATE_FILE.parent.mkdir(exist_ok=True)
        STATE_FILE.write_text(str(time.time()))
        print(f"[fault lab] {datetime.now():%H:%M:%S} fault removed", flush=True)

    print("[fault lab] waiting 15 s for the last telemetry to arrive ...", flush=True)
    time.sleep(15)
    window_start = t0 - BASELINE_S
    telemetry = recorder.record(case_id, window_start, t_end)
    path = case_io.save_telemetry(LIVE_DATASET, telemetry)
    labels.write_label(LIVE_DATASET, {
        "case_id": case_id, "dataset": "demo_app",
        "fault_kind": name, "fault_group": group_of(name) if name != "normal" else "normal",
        "root_causes": [fault["target"]] if fault["target"] else [],
        "fault_start_s": round(t0 - window_start), "duration_s": round(t_end - t0),
        "injected_at": datetime.fromtimestamp(t0).isoformat(timespec="seconds"),
        "details": {"what": fault["what"]},
    })
    n_spans = sum(len(t["spans"]) for t in telemetry["traces"])
    print(f"[fault lab] recorded {telemetry['steps']} metric steps, {len(telemetry['traces'])} traces "
          f"({n_spans} spans), {len(telemetry['logs'])} log lines")
    print(f"[fault lab] telemetry -> {path}")
    print(f"[fault lab] true answer (SHA-256 hashed) -> {LIVE_DATASET}/labels/{case_id}.json")
    print("[fault lab] now run:  make diagnose   (and  make diagnose-nodb  to switch off DB evidence)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("inject")
    p.add_argument("name", choices=sorted(LIVE_FAULTS))
    p.add_argument("--duration", type=int, default=120, help="seconds the fault stays on")
    a = ap.parse_args()
    if a.cmd == "list":
        print("Live faults (implemented):")
        for k, f in LIVE_FAULTS.items():
            print(f"  {k:<15} [{group_of(k) if k != 'normal' else '-':<12}] root cause: {f['target']}: {f['what']}")
        print("\nTODO (planned, simulator only for now): " + ", ".join(TODO_FAULTS))
    else:
        inject(a.name, a.duration)


if __name__ == "__main__":
    main()
