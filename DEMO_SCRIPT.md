# 5-minute demo script (Zeroth Review)

## Before the review (10 minutes earlier)

```bash
cd "$HOME/Downloads/VS Projects/CloudSleuth-Zeroth-Prototype"
make demo                    # check the offline demo works (takes a few seconds)
make up                      # only if Docker Desktop is running; wait 2+ minutes
make fault NAME=db_lock      # optional: a fresh live case (~2.5 min), so 'make diagnose' is instant later
```

Make the terminal font big. Keep `README.md` and `ARCHITECTURE.md` open in the editor.
**If Docker fails, skip step 4.** Steps 1–3 and 5 need no Docker and no internet.

---

## 1. What it is (0:00 – 0:40)

**Say:** "When a microservice app breaks, many services look unhealthy at the same time.
CloudSleuth tries to find the one that *caused* it, using evidence: metrics, traces, logs,
recent changes and database stats. This is our early prototype. It works end to end on two datasets:
our own simulator, and a small live app in Docker that we break on purpose."

Show `ARCHITECTURE.md` diagram: "Five parts. The ones marked BUILT are in this repo;
PLANNED ones are for the next reviews."

## 2. Offline demo: dataset + evaluation (0:40 – 2:00)

**Type:**
```bash
make data
make eval
```

**Say while it runs:**
- "The simulator just generated 144 cases: 16 fault kinds in 8 groups, 8 cases each, plus 16 normal cases.
  It adds noise: missing points, one-off spikes, lost traces, unrelated deploys, and some mild faults."
- "The true answers are in a *separate* folder with a SHA-256 hash of every file. The diagnosis
  code never opens that folder; a test checks it."
- Point at the table: "Method D is our rule-based ranking. We compare it with two baselines:
  'loudest alert' (blame the service with the biggest jump) and random. Every number here is computed
  right now by running the code."
- Point at the **'D, no DB evidence'** row and the **database** column: "If we switch off database
  evidence, database faults are not found at all. That is our motivation."
- **Be honest:** "These simulator numbers are optimistic, because we wrote both the simulator and the rules.
  They are a sanity check. Real numbers will come from the independent benchmark, which is planned."

## 3. The database-lock story (2:00 – 3:00)

**Type:**
```bash
make story
```

**Say:**
- Part 1 (DB evidence OFF): "A table in Postgres is locked. Inventory's queries wait on that lock.
  Without database data the waiting looks like inventory's own work, so it blames **inventory**. Wrong."
- Part 2 (DB evidence ON): "Same case. Now the waiting is the database's own time, and lock waits are up.
  It ranks **postgres** first, fault type **db_lock**."
- Point at the EVIDENCE REPORT: "Each cause comes with supporting and contradicting evidence, so a
  human can check the reasoning."
- Point at "Confidence": "This is only a raw score. It is **not calibrated yet**. Calibration and a
  'not sure' answer are planned."

## 4. Live demo app (3:00 – 4:00), only if Docker is up

**Type:**
```bash
make ps                       # show the containers: 6 services, Postgres, collector, Prometheus, Jaeger, Loki
make faults                   # the 6 live faults (others are TODO)
make diagnose                 # newest live case, DB evidence ON
make diagnose-nodb            # same case, DB evidence OFF
```

**Say:** "This is real traffic through real services, instrumented with OpenTelemetry. The fault lab
locked the inventory table for two minutes and wrote down what it did in a separate hashed label.
The recorder saved Prometheus metrics (5 s), Jaeger traces and Loki logs. Same diagnosis code, same story:
OFF blames inventory, ON finds postgres."

Optional: open Jaeger at http://localhost:16686 and show a slow trace.

(If there is time and the guide asks for a fresh fault: `make fault NAME=slow_service` takes ~2.5 minutes.)

## 5. Viewer + what is planned (4:00 – 5:00)

**Type:** `make viewer`, then open http://localhost:8000

Pick `simulator` → a case → *Run diagnosis*. Tick *switch off database evidence* → run again.
Click *Reveal true answer*.

**Say:** "This is a simple viewer; the React dashboard is planned. Next we plan: the learned ranker
(method G), calibrated confidence with 'not sure', testing on the OpenTelemetry Astronomy Shop,
comparison with MicroRCA, CIRCA and BARO, and proper statistics: Wilson intervals, McNemar, bootstrap."

---

## Likely questions

- **"Why are the simulator numbers so high?"** We built the simulator and the rules from the same
  understanding, so it is easy for our own rules. That is why we planned an independent benchmark
  and statistical tests.
- **"Can the code cheat by reading the answer?"** No. Telemetry and labels are separate folders; the core
  only gets a telemetry file; `tests/test_no_label_access.py` checks it; labels are SHA-256 hashed
  (`cd data/simulator/labels && shasum -a 256 -c SHA256SUMS`).
- **"What is method D?"** Hand-written rules. Each candidate collects evidence (own time up, errors start
  here, network delay on calls into it, no answer, CPU/memory, restarts, recent change, DB lock waits)
  and contradicting evidence (only waiting on others, a service it calls is worse, DB stats normal).
  Score = support − contradict. See `core/ranking.py`.
- **"Why median/MAD?"** It is not thrown off by spikes and outliers, unlike mean/standard deviation.
  We also require 3 unusual readings in a row, so one spike is ignored.
- **"Is the confidence calibrated?"** Not yet. It is a raw score. Calibration is planned.
- **"How much code is it?"** The diagnosis core is about 630 lines of Python (`cloudsleuth_zeroth/core/`).
- **"Anything you learned from the live app?"** Yes: during the DB lock, postgres-exporter's per-table
  queries waited on the same lock and *all* DB stats disappeared. We switched those collectors off.
  It shows why monitoring the database is hard exactly when it matters.
