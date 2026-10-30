# Architecture: CloudSleuth-Zeroth-Prototype

Five parts. Each is marked **BUILT** (in this repo, working) or **PLANNED** (not built yet).

```
 ┌───────────────────────── 1. TARGET APP ─────────────────────────┐
 │  Simulator (BUILT)        Demo app in Docker (BUILT)             │
 │  16 fault kinds           gateway -> orders -> inventory          │
 │  144 cases                                 -> payments            │
 │                           orders -> jobs table -> worker          │
 │                           + PostgreSQL + load generator           │
 │  OpenTelemetry Demo / Astronomy Shop (PLANNED)                    │
 └──────────────┬──────────────────────────────┬────────────────────┘
                │ telemetry                    │ OTLP
 ┌──────────────▼────────── 2. OBSERVABILITY ──▼────────────────────┐
 │  OTel SDK in every service -> OTel Collector -> Prometheus (5 s)  │
 │                                              -> Jaeger (traces)   │
 │                                              -> Loki (logs)       │
 │  postgres-exporter -> Prometheus (DB stats: lock waits, ...)      │
 │  Recorder: saves a snapshot per fault in the SAME format as the   │
 │  simulator (BUILT)                                                 │
 └──────────────┬────────────────────────────────────────────────────┘
                │ telemetry file (no answers inside)
 ┌──────────────▼────────────── 3. CORE ─────────────────────────────┐
 │  anomaly detection -> snapshot -> trace attribution -> ranking     │
 │  (median/MAD,         (before /    (own time vs      (method D,    │
 │   3 readings in a row) incident)    waiting time)     rules)  BUILT│
 │  --no-db-evidence switch (BUILT)                                   │
 │  learned ranker "method G" (PLANNED)                               │
 │  calibrated confidence + "not sure" abstention (PLANNED)           │
 └──────────────┬────────────────────────────────────────────────────┘
 ┌──────────────▼────────────── 4. OUTPUTS ──────────────────────────┐
 │  ranked causes, fault type, evidence report, raw score (BUILT)     │
 │  CLI text / JSON (BUILT), simple FastAPI + HTML viewer (BUILT)     │
 │  React dashboard (PLANNED), safe remediation suggestions (PLANNED) │
 └────────────────────────────────────────────────────────────────────┘
 ┌──────────────────── 5. RESEARCH / TESTING LAYER ──────────────────┐
 │  labels kept separate + SHA-256 (BUILT), fault lab (BUILT, 6 live) │
 │  evaluation: top-1 / top-3, baselines loudest-alert + random (BUILT)│
 │  pytest tests (BUILT)                                              │
 │  MicroRCA / CIRCA / BARO comparison (PLANNED)                      │
 │  Wilson CI, McNemar, bootstrap (PLANNED); independent benchmark    │
 │  (PLANNED)                                                         │
 └────────────────────────────────────────────────────────────────────┘
```

## 1. Target app: BUILT (simulator + demo app), Astronomy Shop PLANNED

**Simulator** (`cloudsleuth_zeroth/simulator/`). A small model of the same service graph.
Every 5-second step has a *state* (own work time per service, DB time, network delay, error
chance, CPU, memory, DB stats). A fault changes the state (`faults.py`); `generate.py` turns the
state into metrics, traces (real parent/child spans), logs, change events and DB stats, then adds
noise: jitter, one-off spikes, 3% missing points, scrape gaps, 8% lost traces, unrelated
"red-herring" deploys/config changes, and 1 in 4 faults at mild strength.

**Demo app** (`demo_app/`). Five FastAPI services + a load generator (6 containers built from one
image) + PostgreSQL. The worker reads jobs from a Postgres table (used as a queue).
Each service has `/admin/...` endpoints that only the fault lab uses.

**PLANNED:** test on the OpenTelemetry Demo (Astronomy Shop).

## 2. Observability: BUILT

- `demo_app/services/common.py`: OpenTelemetry SDK. Traces (FastAPI + requests auto-instrumented,
  DB calls as manual `db.system=postgresql` spans), metrics (request count, duration histogram,
  CPU, memory), logs (OTLP).
- `demo_app/config/otel-collector.yaml`: Collector fans out to Jaeger (traces),
  Prometheus exporter (metrics) and Loki (logs, native OTLP).
- `demo_app/config/prometheus.yml`: 5 s scrape of the collector and postgres-exporter.
- `demo_app/config/postgres-exporter-queries.yaml`: an extra `pg_lock_waits` metric.
  The exporter's per-table collectors are switched off: in our first live test they waited
  on the very table lock we injected, and **all** DB stats vanished during the incident.
- `faultlab/recorder.py`: pulls a time window from Prometheus, Jaeger (api/v3) and Loki and saves it
  as one telemetry JSON file, in the simulator's format.

## 3. Core: BUILT (method D); method G and calibration PLANNED

`cloudsleuth_zeroth/core/` (about 630 lines). It reads **only** a telemetry file.

| Step | File | What it does |
|---|---|---|
| 1 Anomaly detection | `anomaly.py` | First third of the window = normal reference. z = (x - median) / MAD-spread. A series is anomalous only if it stays past z = 4 for **3 readings in a row** (a single spike is ignored). A service that stops reporting *all* its metrics, or restarts 2+ times (from logs), is flagged too. |
| 2 Snapshot | `snapshot.py` | Prepares the data; `--no-db-evidence` drops DB stats, removes the DB as a candidate and treats DB spans as the caller's own work. Splits into a "before" and an "incident" window around the onset. |
| 3 Trace attribution | `attribution.py` | For each span: own time = duration - time covered by children. DB spans -> the database's own time. A client span's own time = network gap -> charged to the callee. Finds where errors START, calls that got no answer, and callers that gave up although the callee was fine. |
| 4 Ranking (method D) | `ranking.py` | For each candidate, collects supporting / contradicting evidence with hand-set weights. Raw score = support - contradict. Guesses the fault type from the evidence of the top cause. |
| 5 Output | `diagnose.py`, `report.py` | Ranked causes, fault type, evidence report, raw score labelled "NOT calibrated yet". |
| Baselines | `baselines.py` | loudest alert (biggest latency/error jump), random (fixed seed per case). |

**PLANNED:** learned ranker (method G), calibrated confidence, "not sure" abstention.

## 4. Outputs: BUILT (CLI, JSON, simple viewer); React dashboard + remediation PLANNED

- `python -m cloudsleuth_zeroth.core.diagnose <file> [--no-db-evidence] [--json]`
- `cloudsleuth_zeroth/viewer/`: one FastAPI app + one plain HTML page.

## 5. Research / testing layer: BUILT (basic); comparisons + statistics PLANNED

- Labels live in `data/<dataset>/labels/`, separate from `telemetry/`, hashed in `SHA256SUMS`
  (check with `shasum -a 256 -c SHA256SUMS`). `labels.py` refuses a label whose hash does not match.
- `faultlab/fault_lab.py`: injects a live fault, records the snapshot, writes the label.
- `cloudsleuth_zeroth/evaluation/evaluate.py`: top-1 / top-3 per method, per fault group,
  normal cases, fault-type accuracy. Every number is computed when you run it.
- `tests/`: pytest, including a test that the core never touches labels.

**PLANNED:** comparison with MicroRCA / CIRCA / BARO; Wilson confidence intervals, McNemar test,
bootstrap; independent benchmark.

## Why the database-lock story matters

When a table is locked, the service that queries it (here `inventory`) gets very slow and
starts failing. A tool that cannot see the database sees only "inventory's own work got
slow" and blames inventory. With DB evidence, the slow time is the database's own time,
lock waits are up, and the database is ranked first. `make story` (simulator) and
`make diagnose` / `make diagnose-nodb` (live) show this on the same case.
