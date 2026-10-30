"""worker: takes jobs from the queue (a Postgres table) and processes them.
Each job is its own trace ("process job")."""

import threading
import time

from opentelemetry.trace import SpanKind

from common import db, log, make_app, own_work, record, tracer

app = make_app()


def process_one():
    t0 = time.perf_counter()
    ok = True
    with tracer.start_as_current_span("process job", kind=SpanKind.CONSUMER):
        try:
            rows = db("SELECT id FROM jobs WHERE NOT done ORDER BY id LIMIT 1", fetch=True)
            if not rows:
                return False
            own_work()
            db("UPDATE jobs SET done = TRUE WHERE id = %s", (rows[0][0],))
        except Exception as e:
            ok = False
            log.error(f"unhandled exception in job handler: {e}")
    record((time.perf_counter() - t0) * 1000, ok)
    return True


def loop():
    while True:
        try:
            if not process_one():
                time.sleep(0.2)
        except Exception as e:                      # keep the worker alive
            log.error(f"worker loop error: {e}")
            time.sleep(1)


threading.Thread(target=loop, daemon=True).start()
