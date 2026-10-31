# STATUS: review-slide claims → where to see them

Status as of the Zeroth Review. **BUILT** = working in this repo. **PLANNED** = not built yet (on purpose).

## Slide: "Work done so far"

| Slide claim | Status | Where to see it |
|---|---|---|
| Found and studied the datasets | BUILT | Dataset 1: `cloudsleuth_zeroth/simulator/`. Dataset 2: `demo_app/` + `faultlab/`. Recorded live cases: `data/demo_app/` |
| Developed the initial architecture | BUILT | [ARCHITECTURE.md](ARCHITECTURE.md) (5 parts, each marked BUILT / PLANNED) |
| Early prototype | BUILT | `cloudsleuth_zeroth/core/` (diagnosis), `make demo`, `make viewer` |
| Discussed expected outcome with guide | Done (meeting) | Expected outputs are what the prototype prints: ranked causes, fault type, evidence report, raw score (`core/report.py`) |
| Completed literature survey | Done (report/slides) | Not code. Baselines from it (MicroRCA, CIRCA, BARO) are PLANNED below |

## Dataset 1: simulator

| Claim | Status | File |
|---|---|---|
| Generates failure cases on demand: metrics, traces, logs, recent changes, DB stats | BUILT | `simulator/generate.py` (`simulate_case`) |
| Small service graph | BUILT | `topology.py` |
| 16 fault kinds in 8 groups | BUILT | `faults.py` (names), `simulator/faults.py` (effects) |
| 144 cases = 128 faulty + 16 normal | BUILT | `simulator/generate.py` (`generate`), check: `make data` |
| Noise and missing data | BUILT | `simulator/generate.py` (`add_noise`, lost traces, scrape gaps, red-herring changes), mild faults in `simulator/faults.py` (`STRENGTH`) |
| Labels in separate files with SHA-256 | BUILT | `labels.py`, `data/simulator/labels/SHA256SUMS` |
| Diagnosis never reads labels | BUILT | `tests/test_no_label_access.py`; `core/diagnose.py` takes a telemetry file only |

## Dataset 2: live demo app

| Claim | Status | File |
|---|---|---|
| 6 services + PostgreSQL (gateway → orders → inventory, payments, worker queue, load generator) | BUILT | `demo_app/services/*.py`, `demo_app/docker-compose.yml` |
| OpenTelemetry instrumentation | BUILT | `demo_app/services/common.py` |
| OTel Collector, Prometheus (5 s), Jaeger, Loki, postgres-exporter | BUILT | `demo_app/config/*`, `demo_app/docker-compose.yml` |
| Fault lab injects faults and records the true answer (separate, SHA-256) | BUILT | `faultlab/fault_lab.py` |
| ≥ 6 live faults incl. DB lock, slow service, crash, CPU hog, bad config, network delay | BUILT | `faultlab/fault_lab.py` (`LIVE_FAULTS`) |
| Other 10 live faults | TODO | `faultlab/fault_lab.py` (`TODO_FAULTS`); they exist in the simulator |
| Recorder saves a telemetry snapshot per fault | BUILT | `faultlab/recorder.py` |

## Early prototype diagnosis

| Claim | Status | File |
|---|---|---|
| Anomaly detection: median/MAD, must persist (not one spike) | BUILT | `core/anomaly.py`; test `tests/test_anomaly.py` |
| Telemetry snapshot | BUILT | `core/snapshot.py` |
| Trace attribution: own time vs waiting time | BUILT | `core/attribution.py`; test `tests/test_attribution.py` |
| Evidence-based ranking (rule-based method D) | BUILT | `core/ranking.py` |
| Output: ranked causes, fault type, evidence report (support + contradict) | BUILT | `core/diagnose.py`, `core/report.py` |
| `--no-db-evidence` reproduces the motivation story | BUILT | `core/snapshot.py`; `make story` (simulator), `make diagnose-nodb` (live); test `tests/test_diagnosis.py` |
| Baselines: loudest alert, random | BUILT | `core/baselines.py` |
| Confidence shown as raw score, "not calibrated yet" | BUILT | `core/diagnose.py` (`CONFIDENCE_NOTE`) |

## Evaluation and viewer

| Claim | Status | File |
|---|---|---|
| Top-1 / top-3 accuracy per method, from real runs | BUILT | `evaluation/evaluate.py`; `make eval` (writes `results/`) |
| Simple viewer (FastAPI, one HTML page) | BUILT | `viewer/app.py`, `viewer/index.html`; `make viewer` |
| Offline demo without Docker / internet | BUILT | `make demo` |
| Tests | BUILT | `tests/`; `make test` |
| Results report from real runs | BUILT | [REPORT.md](REPORT.md), written by `evaluation/report.py`; `make report` |

## Planned (not built, on purpose)

| Item | Status |
|---|---|
| OpenTelemetry Demo (Astronomy Shop) testing | PLANNED |
| Learned ranker (method G) | PLANNED |
| Calibrated confidence and "not sure" abstention | PLANNED |
| Safe remediation | PLANNED |
| React dashboard | PLANNED |
| Comparison with MicroRCA / CIRCA / BARO | PLANNED |
| Statistical tests: Wilson CI, McNemar, bootstrap | PLANNED |
| Independent benchmark | PLANNED |

## Known limitations (be ready to say these)

- Simulator numbers are optimistic: we built the simulator and the rules, and adjusted the
  rules while looking at the simulator.
- Method D weights are hand-set; the raw score is not a probability.
- Live dataset is small (one case per fault run) and uses only 6 of 16 fault kinds.
- One fault-type rule was changed after seeing a live case: in the live cpu_hog run the starved
  service also answered late (looked like network delay), so CPU/memory evidence is now checked
  before network evidence (`core/ranking.py`, `guess_fault_type`).
- The restart signal (`core/anomaly.py`, `detect_restarts`) was added after the live
  service_crash run was first reported as "normal": Docker restarted the service in ~0.5 s,
  so no metric stayed unusual for 3 readings; only the logs showed the crash loop.
- Trace sampling in the recorder is simple (a few traces per 20 s).
