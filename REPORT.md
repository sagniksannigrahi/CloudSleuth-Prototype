# CloudSleuth-Zeroth-Prototype: Prototype Results Report

**Project:** CloudSleuth: Evidence-Based Root-Cause Analysis for Microservices, with Calibrated Confidence and an Independent Benchmark  
**Students:** Sagnik Sannigrahi (RA2311003011709), Malik Inam Ul Haq (RA2311003011727)  
**Batch:** B763, Dept. of Computing Technologies (CTECH), SRM IST Kattankulathur  
**Guide:** Dr. A. M. Vidhyalakshmi  
**Stage:** Zeroth Review, early prototype  
**Generated:** 31 October 2026, 10:32 from commit `8993e27` (Python 3.14.6) by `make report`

> Every number and result row below was produced by running the prototype when this report was generated. Re-run `make report` to reproduce it.

## 1. Summary

- On the **simulator** (144 cases), method D put a true root cause first in **124/128 = 96.9%** of fault cases and in the top 3 in **127/128 = 99.2%**. The loudest-alert baseline managed 39/128 = 30.5% and random 22/128 = 17.2%.
- **Database evidence matters:** on database faults, method D found the cause in 16/16 cases with DB evidence and 0/16 without it.
- Method D correctly reported "no incident" on 16/16 = 100.0% of normal cases (the baselines always name a culprit).
- On the **live demo app** (7 recorded cases), method D found the injected cause first in **6/6 = 100.0%** of fault runs and called 1/1 = 100.0% normal runs normal.
- **Caution:** these are early, optimistic numbers. We built the simulator and the rules ourselves, and the live set is very small. They show the pipeline works; they are not a final result (see section 7).

## 2. What was tested

**Pipeline (method D):** anomaly detection (median/MAD, must stay unusual for 3 readings) → telemetry snapshot → trace attribution (each service's own time vs time waiting on others) → evidence-based ranking with hand-set rules → ranked causes, fault type, evidence report and a raw score (not calibrated).

**Compared with:**
- *D, no DB evidence*: the same method with all database data switched off (`--no-db-evidence`).
- *Loudest alert*: blames the service whose latency or error rate jumped the most.
- *Random*: a random order of candidates (fixed seed per case).

**Datasets:**
- *Simulator*: 16 fault kinds in 8 groups × 8 cases + 16 normal cases, with noise, missing data, mild faults and unrelated changes. Candidates: 5 services + the database.
- *Live demo app*: 5 OpenTelemetry-instrumented services + load generator + PostgreSQL in Docker, observed with OTel Collector, Prometheus (5 s), Jaeger, Loki and postgres-exporter. A fault lab injects one fault for 120 s and the recorder saves the 2 minutes before plus the fault period.

**Measures:** top-1 accuracy (first-ranked cause is a true cause), top-3 accuracy, normal cases reported as normal, and the fault-type guess. True answers are stored separately from telemetry, SHA-256 hashed, and read only by the evaluation, never by the diagnosis.

## 3. Results on the simulator


| Method | Top-1 accuracy | Top-3 accuracy | Normal cases called normal |
|----------------------|--------------------|--------------------|----------------------------|
| D (evidence rules) | 124/128 = 96.9% | 127/128 = 99.2% | 16/16 = 100.0% |
| D, no DB evidence | 106/128 = 82.8% | 111/128 = 86.7% | 16/16 = 100.0% |
| Loudest alert | 39/128 = 30.5% | 84/128 = 65.6% | 0/16 = 0.0% |
| Random | 22/128 = 17.2% | 76/128 = 59.4% | 0/16 = 0.0% |

**Top-1 accuracy per fault group (hits / cases):**

| Method | availability | database | delay | errors | multiple | network | resources | settings |
|----------------------|--------------|--------------|--------------|--------------|--------------|--------------|--------------|--------------|
| D (evidence rules) | 16/16 | 16/16 | 16/16 | 14/16 | 16/16 | 14/16 | 16/16 | 16/16 |
| D, no DB evidence | 16/16 | 0/16 | 16/16 | 14/16 | 14/16 | 14/16 | 16/16 | 16/16 |
| Loudest alert | 0/16 | 0/16 | 10/16 | 6/16 | 5/16 | 1/16 | 6/16 | 11/16 |
| Random | 3/16 | 1/16 | 2/16 | 3/16 | 5/16 | 1/16 | 3/16 | 4/16 |

- Method D fault-type guess (single-fault cases): exact kind 104/112 = 92.9%, right group 107/112 = 95.5%
- Method D top-1 on MILD faults only: 28/32 = 87.5%
- Confidence: method D gives a raw score only; it is NOT calibrated yet (planned).

**Reading the table:**
- Method D is far ahead of both baselines (top-1 124/128 = 96.9% vs 39/128 = 30.5% and 22/128 = 17.2%).
- Without DB evidence, top-1 drops to 106/128 = 82.8%. Groups that lost cases: database (16 → 0 of 16), multiple (16 → 14 of 16). With no database data, the service that *calls* the database is blamed instead.
- Mild faults are harder: method D's top-1 on mild cases was 28/32 = 87.5%.
- Groups where the loudest alert never ranked the true cause first: availability, database. In these the loudest symptom tends to appear at a caller, not at the cause.

## 4. The database-lock story

This is our motivation: when a database table is locked, the service that queries it becomes slow and fails. Without database evidence that slowness looks like the service's own work.

### Simulator (case `sim-045`)

True answer (from the hashed label, read after diagnosis): `db_lock` → `postgres`

| | DB evidence OFF | DB evidence ON |
|---|---|---|
| Top cause | `inventory` (**wrong**) | `postgres` (right) |
| Fault type guessed | `slow_service` | `db_lock` |
| Raw score (not calibrated) | 4.5 | 7.5 |
| Ranking | inventory → gateway → payments → worker | postgres → gateway → inventory → orders |

Evidence report with DB evidence OFF (top cause `inventory`):
- supports [4.0]: inventory's OWN work time per request rose from 18 ms to 1258 ms
- supports [0.5]: latency_p95_ms unusual from t=155s: normal 26.135 -> up to 5336.51 (score 1062.1, stayed unusual)
- contradicts: (none)

Evidence report with DB evidence ON (top cause `postgres`):
- supports [4.0]: postgres's OWN work time per request rose from 12 ms to 847 ms
- supports [3.0]: lock_waits unusual from t=155s: normal 0 -> up to 7 (score 7, stayed unusual)
- supports [0.5]: active_connections unusual from t=165s: normal 6.428 -> up to 15.966 (score 6.4, stayed unusual)
- contradicts: (none)

### Live demo app (real PostgreSQL table lock) (case `live-20261031-012855`)

True answer (from the hashed label, read after diagnosis): `db_lock` → `postgres`

| | DB evidence OFF | DB evidence ON |
|---|---|---|
| Top cause | `inventory` (**wrong**) | `postgres` (right) |
| Fault type guessed | `exception_burst` | `db_lock` |
| Raw score (not calibrated) | 9.0 | 13.5 |
| Ranking | inventory → payments → gateway → worker | postgres → payments → gateway → inventory |

Evidence report with DB evidence OFF (top cause `inventory`):
- supports [4.0]: inventory's OWN work time per request rose from 3 ms to 2740 ms
- supports [4.0]: errors START in inventory itself in 61% of requests (before: 0%)
- supports [0.5]: error_rate unusual from t=135s: normal 0.045 -> up to 1 (score 14.3, stayed unusual)
- supports [0.5]: 522 error logs from inventory's own code
- contradicts: (none)

Evidence report with DB evidence ON (top cause `postgres`):
- supports [4.0]: postgres's OWN work time per request rose from 3 ms to 1991 ms
- supports [4.0]: errors START in postgres itself in 61% of requests (before: 0%)
- supports [3.0]: lock_waits unusual from t=125s: normal 0 -> up to 15 (score 15, stayed unusual)
- supports [0.5]: active_connections unusual from t=125s: normal 0 -> up to 16 (score 10.7, stayed unusual)
- supports [2.0]: max_tx_duration_s unusual from t=130s: normal 0 -> up to 117.557 (score 117.6, stayed unusual)
- contradicts: (none)

## 5. Results on the live demo app

Per recorded case (✓ = top cause is the true cause; for the normal run ✓ means "no incident" was reported):

| Case | Injected fault | True cause | D (DB on) | Fault type guessed | D (DB off) | Loudest alert | Random |
|---|---|---|---|---|---|---|---|
| `live-20261031-012855` | db_lock | `postgres` | `postgres` ✓ | db_lock | `inventory` ✗ | `orders` ✗ | `orders` ✗ |
| `live-20261031-013340` | slow_service | `payments` | `payments` ✓ | slow_service | `payments` ✓ | `payments` ✓ | `worker` ✗ |
| `live-20261031-013755` | cpu_hog | `inventory` | `inventory` ✓ | cpu_hog | `inventory` ✓ | `gateway` ✗ | `inventory` ✓ |
| `live-20261031-014210` | bad_config | `orders` | `orders` ✓ | bad_config | `orders` ✓ | `gateway` ✗ | `inventory` ✗ |
| `live-20261031-014626` | network_delay | `inventory` | `inventory` ✓ | network_delay | `inventory` ✓ | `gateway` ✗ | `inventory` ✓ |
| `live-20261031-015042` | service_crash | `payments` | `payments` ✓ | service_crash | `payments` ✓ | `gateway` ✗ | `gateway` ✗ |
| `live-20261031-015457` | normal | `(none)` | `(normal)` ✓ | - | `(normal)` ✓ | `gateway` ✗ | `worker` ✗ |


| Method | Top-1 accuracy | Top-3 accuracy | Normal cases called normal |
|----------------------|--------------------|--------------------|----------------------------|
| D (evidence rules) | 6/6 = 100.0% | 6/6 = 100.0% | 1/1 = 100.0% |
| D, no DB evidence | 5/6 = 83.3% | 5/6 = 83.3% | 1/1 = 100.0% |
| Loudest alert | 1/6 = 16.7% | 3/6 = 50.0% | 0/1 = 0.0% |
| Random | 2/6 = 33.3% | 4/6 = 66.7% | 0/1 = 0.0% |

**Top-1 accuracy per fault group (hits / cases):**

| Method | availability | database | delay | network | resources | settings |
|----------------------|--------------|--------------|--------------|--------------|--------------|--------------|
| D (evidence rules) | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| D, no DB evidence | 1/1 | 0/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| Loudest alert | 0/1 | 0/1 | 1/1 | 0/1 | 0/1 | 0/1 |
| Random | 0/1 | 0/1 | 0/1 | 1/1 | 1/1 | 0/1 |

- Method D fault-type guess (single-fault cases): exact kind 6/6 = 100.0%, right group 6/6 = 100.0%
- Method D top-1 on MILD faults only: n/a
- Confidence: method D gives a raw score only; it is NOT calibrated yet (planned).

## 6. What we learned from the live runs

These came up while running the live demo app and changed the prototype. We record them here because they affect how the numbers should be read.

1. **Database monitoring went blind during the lock.** postgres-exporter's per-table queries waited on the same table lock, every scrape timed out, and all DB stats disappeared exactly when they were needed. We switched those collectors off. Lesson: the monitoring path can share the failure.
2. **Fast crash loops slip past metric checks.** Docker restarted the crashed service in about 0.5 s, so no metric stayed unusual for 3 readings; the first diagnosis said "normal". Only the logs showed repeated restarts, so a restart signal from logs was added.
3. **A CPU hog looks like network delay.** The starved process answered late, which made calls into it look slow on the network. The fault-type rules now check CPU/memory before network.
4. **Some faults leave no logs.** Live runs with zero log lines in their snapshot: slow_service, cpu_hog, network_delay, normal. For these, traces and metrics carried all the evidence.

Because fixes 2 and 3 were made after seeing these live cases, the live results above are not an unbiased test of method D.

## 7. Limitations

- **Optimistic simulator.** The same team wrote the simulator and the rules, and the rules were adjusted while looking at the simulator.
- **Hand-set weights.** Method D's evidence weights are first guesses; the raw score is not a probability.
- **Small live set.** One run per fault, only 6 of the 16 fault kinds can be injected live, one service graph.
- **No statistics yet.** No confidence intervals or significance tests, so small differences mean little.
- **Recorder tied to our app.** Service names and metric names are fixed for the demo app.

## 8. Next steps (planned, not built)

- Testing on the OpenTelemetry Demo (Astronomy Shop), as an independent benchmark.
- Learned ranker (method G) to learn the evidence weights.
- Calibrated confidence and a "not sure" answer.
- Comparison with MicroRCA, CIRCA and BARO.
- Statistical tests: Wilson confidence intervals, McNemar test, bootstrap.
- Remaining 10 live faults, safe remediation suggestions, and a React dashboard.

## 9. How to reproduce

```bash
make data      # regenerate the 144 simulator cases
make report    # re-run everything and rewrite this REPORT.md
make demo      # evaluation table + database-lock story in the terminal
make up && make fault NAME=db_lock && make diagnose   # a new live case (Docker)
```
