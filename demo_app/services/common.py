"""Shared code for every demo-app service.

  * OpenTelemetry: traces, metrics and logs are sent (OTLP) to the OTel Collector
  * metrics: request count, request duration, process CPU and memory
  * db(): runs SQL and records it as a database span (db.system=postgresql)
  * call(): HTTP call to another service (traced automatically)
  * fault switches + /admin endpoints used by the fault lab
"""

import functools
import logging
import os
import random
import sys
import threading
import time

import psutil
import psycopg2
import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.metrics import Observation
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode
from psycopg2.pool import ThreadedConnectionPool

SERVICE = os.environ.get("SERVICE_NAME", "unknown")
RESOURCE = Resource.create({"service.name": SERVICE})

# ---------------------------------------------------------------- traces
_tp = TracerProvider(resource=RESOURCE)
_tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(), schedule_delay_millis=1000))
trace.set_tracer_provider(_tp)
tracer = trace.get_tracer(SERVICE)
RequestsInstrumentor().instrument()

# ---------------------------------------------------------------- metrics
_reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=5000)
metrics.set_meter_provider(MeterProvider(resource=RESOURCE, metric_readers=[_reader]))
_meter = metrics.get_meter(SERVICE)
REQUESTS = _meter.create_counter("cs.requests", description="requests handled")
DURATION = _meter.create_histogram("cs.request.duration", unit="ms", description="request duration")
_proc = psutil.Process()
_proc.cpu_percent(None)
_meter.create_observable_gauge(
    "cs.process.cpu", callbacks=[lambda _: [Observation(_proc.cpu_percent(None) / 100, {"service": SERVICE})]])
_meter.create_observable_gauge(
    "cs.process.memory_mb", callbacks=[lambda _: [Observation(_proc.memory_info().rss / 1e6, {"service": SERVICE})]])


def record(duration_ms, ok):
    REQUESTS.add(1, {"service": SERVICE, "status": "ok" if ok else "error"})
    DURATION.record(duration_ms, {"service": SERVICE})


# ---------------------------------------------------------------- logs
_lp = LoggerProvider(resource=RESOURCE)
_lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(), schedule_delay_millis=1000))
log = logging.getLogger(SERVICE)
log.setLevel(logging.INFO)
log.addHandler(LoggingHandler(logger_provider=_lp))
log.addHandler(logging.StreamHandler(sys.stdout))

# ---------------------------------------------------------------- faults
FAULT = {"slow_ms": 0, "error_rate": 0.0, "cpu_hog": False}
CONFIG = {}


def _hog():
    x = 0
    while FAULT["cpu_hog"]:
        x = (x * 31 + 7) % 1000003            # burn CPU (holds the Python GIL)


def own_work(loops=20000):
    """The service's own work: a bit of CPU, plus any injected slowness/errors."""
    x = 0
    for i in range(loops):
        x += i * i
    if FAULT["slow_ms"]:
        time.sleep(FAULT["slow_ms"] / 1000)
    if random.random() < FAULT["error_rate"]:
        raise RuntimeError("NullPointer in business logic")


# ---------------------------------------------------------------- calls
class UpstreamError(Exception):
    def __init__(self, service, reason):
        super().__init__(f"call to {service} failed: {reason}")
        self.service, self.reason = service, reason


def call(service, path, payload, timeout_s):
    try:
        r = requests.post(f"http://{service}:8000{path}", json=payload, timeout=float(timeout_s))
    except requests.Timeout:
        raise UpstreamError(service, f"timed out after {float(timeout_s) * 1000:.0f} ms")
    except requests.ConnectionError:
        raise UpstreamError(service, "connection refused")
    if r.status_code >= 500:
        raise UpstreamError(service, f"upstream returned {r.status_code}")
    return r.json()


_pool = None
_pool_lock = threading.Lock()


def db(sql, params=(), fetch=False):
    """Run one SQL statement inside a database client span."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadedConnectionPool(1, 40, os.environ["DATABASE_URL"],
                                           options="-c statement_timeout=3000")
    conn = _pool.getconn()
    try:
        with tracer.start_as_current_span(
                "SQL " + sql.split()[0], kind=SpanKind.CLIENT,
                attributes={"db.system": "postgresql", "db.statement": sql, "peer.service": "postgres"}) as span:
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall() if fetch else None
                conn.commit()
                return rows
            except Exception as e:
                conn.rollback()
                span.set_status(Status(StatusCode.ERROR, str(e).strip()))
                raise
    finally:
        _pool.putconn(conn)


def safe(fn):
    """Turn exceptions into HTTP 500 + an error log (like a real service)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except UpstreamError as e:
            log.error(str(e))
        except psycopg2.Error as e:
            log.error(f"database error: {str(e).strip().splitlines()[0]}")
        except Exception as e:
            log.error(f"unhandled exception in request handler: {e}")
        trace.get_current_span().set_status(Status(StatusCode.ERROR))
        return JSONResponse({"error": "internal error"}, status_code=500)
    return wrapper


# ---------------------------------------------------------------- the app
def make_app(config=None):
    CONFIG.update(config or {})
    app = FastAPI(title=SERVICE)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,admin", exclude_spans=["receive", "send"])

    @app.middleware("http")
    async def measure(request: Request, call_next):
        if request.url.path.startswith(("/admin", "/health")):
            return await call_next(request)
        t0 = time.perf_counter()
        response = await call_next(request)
        record((time.perf_counter() - t0) * 1000, response.status_code < 500)
        return response

    @app.get("/health")
    def health():
        return {"service": SERVICE, "ok": True}

    @app.post("/admin/fault")
    def set_fault(body: dict):
        """Used by the fault lab only."""
        if body.get("crash"):
            log.error("fatal error, process exiting")
            _lp.force_flush()
            threading.Timer(0.2, os._exit, [1]).start()
            return {"crashing": True}
        for key in FAULT:
            if key in body:
                FAULT[key] = body[key]
        if body.get("cpu_hog"):
            for _ in range(2):
                threading.Thread(target=_hog, daemon=True).start()
        return FAULT

    @app.post("/admin/config")
    def set_config(body: dict):
        """A config change. Like a real config system, every change is logged."""
        for key, value in body.items():
            log.warning(f"CHANGE config {key}: {CONFIG.get(key)} -> {value}")
            CONFIG[key] = value
        return CONFIG

    @app.post("/admin/reset")
    def reset():
        FAULT.update(slow_ms=0, error_rate=0.0, cpu_hog=False)
        return FAULT

    log.info("service starting")
    return app
