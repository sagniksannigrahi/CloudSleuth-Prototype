"""Write REPORT.md from a fresh run of the prototype.

Every number and every result row in the report is produced by running the
code in this file (simulator evaluation, live-case diagnosis, DB-lock story).
Nothing is typed in by hand. Fixed text (method, findings, limitations) does
not contain results.

Run:  python -m cloudsleuth_zeroth.evaluation.report     (or: make report)
"""

import platform
import subprocess
from datetime import datetime
from pathlib import Path

from .. import case_io, labels
from ..core.diagnose import diagnose
from .evaluate import as_table, score_dataset
from .evaluate import pct as _pct
from .story import find_db_lock_case

SIM, LIVE = "data/simulator", "data/demo_app"


def pct(a, b):
    return " ".join(_pct(a, b).split())                     # "6/6 = 100.0%", no padding


def _tables(res):
    """The evaluation tables as real Markdown (notes become bullet points)."""
    out = []
    for line in as_table(res).splitlines()[1:]:             # skip the "Dataset:" line
        line = " ".join(line.split()) if line.startswith("|") and "---" not in line else line
        if line and not line.startswith("|"):
            line = " ".join(line.split())
            line = f"**{line}**" if line.endswith(":") else f"- {line}"
        out.append(line)
    return out


def _git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def _load(ds, case):
    return case_io.load_telemetry(case_io.telemetry_path(ds, case))


def _top(r):
    return r["ranking"][0]["node"] if r["incident"] and r["ranking"] else "(normal)"


def _story(ds):
    """Diagnose the DB-lock case with DB evidence OFF and ON."""
    case = find_db_lock_case(ds)
    if not case:
        return None
    tele = _load(ds, case)
    off, on = diagnose(tele, use_db=False), diagnose(tele, use_db=True)
    return case, labels.read_label(ds, case), off, on


def _story_md(title, story):
    case, truth, off, on = story
    ok = lambda r: "right" if r.get("top_cause") in truth["root_causes"] else "**wrong**"  # noqa: E731
    out = [f"### {title} (case `{case}`)", "",
           f"True answer (from the hashed label, read after diagnosis): `{truth['fault_kind']}` → "
           f"`{', '.join(truth['root_causes'])}`", "",
           "| | DB evidence OFF | DB evidence ON |", "|---|---|---|",
           f"| Top cause | `{off.get('top_cause')}` ({ok(off)}) | `{on.get('top_cause')}` ({ok(on)}) |",
           f"| Fault type guessed | `{off.get('fault_type')}` | `{on.get('fault_type')}` |",
           f"| Raw score (not calibrated) | {off.get('raw_score')} | {on.get('raw_score')} |",
           "| Ranking | " + " → ".join(x["node"] for x in off["ranking"][:4]) + " | "
           + " → ".join(x["node"] for x in on["ranking"][:4]) + " |", ""]
    for name, r in (("OFF", off), ("ON", on)):
        rep = r["evidence_report"]
        out.append(f"Evidence report with DB evidence {name} (top cause `{rep['cause']}`):")
        out += [f"- supports [{e['weight']}]: {e['text']}" for e in rep["support"]]
        out += [f"- contradicts [{e['weight']}]: {e['text']}" for e in rep["contradict"]] or ["- contradicts: (none)"]
        out.append("")
    return out


def _live_rows(ds):
    rows = ["| Case | Injected fault | True cause | D (DB on) | Fault type guessed | D (DB off) | Loudest alert | Random |",
            "|---|---|---|---|---|---|---|---|"]
    for case in case_io.list_cases(ds):
        lab = labels.read_label(ds, case)
        tele = _load(ds, case)
        d = diagnose(tele)
        truth = ", ".join(lab["root_causes"]) or "(none)"
        mark = lambda r: f"`{_top(r)}`" + (" ✓" if _top(r) in lab["root_causes"]  # noqa: E731
                                           or (not lab["root_causes"] and not r["incident"]) else " ✗")
        rows.append(f"| `{case}` | {lab['fault_kind']} | `{truth}` | {mark(d)} | "
                    f"{d.get('fault_type', '-')} | {mark(diagnose(tele, use_db=False))} | "
                    f"{mark(diagnose(tele, method='loudest'))} | {mark(diagnose(tele, method='random'))} |")
    return rows


def build():
    sim, live = score_dataset(SIM), score_dataset(LIVE) if case_io.list_cases(LIVE) else None
    d, nodb, loud, rnd = (sim["methods"][k] for k in
                          ("D (evidence rules)", "D, no DB evidence", "Loudest alert", "Random"))
    db_d, db_nodb = d["by_group"]["database"], nodb["by_group"]["database"]
    sim_story, live_story = _story(SIM), (_story(LIVE) if live else None)

    L = ["# CloudSleuth-Zeroth-Prototype: Prototype Results Report", "",
         "**Project:** CloudSleuth: Evidence-Based Root-Cause Analysis for Microservices, "
         "with Calibrated Confidence and an Independent Benchmark  ",
         "**Students:** Sagnik Sannigrahi (RA2311003011709), Malik Inam Ul Haq (RA2311003011727)  ",
         "**Batch:** B763, Dept. of Computing Technologies (CTECH), SRM IST Kattankulathur  ",
         "**Guide:** Dr. A. M. Vidhyalakshmi  ",
         "**Stage:** Zeroth Review, early prototype  ",
         f"**Generated:** {datetime.now():%d %B %Y, %H:%M} from commit `{_git_commit()}` "
         f"(Python {platform.python_version()}) by `make report`", "",
         "> Every number and result row below was produced by running the prototype when this report was "
         "generated. Re-run `make report` to reproduce it.", "",
         "## 1. Summary", "",
         f"- On the **simulator** ({sim['cases']} cases), method D put a true root cause first in "
         f"**{pct(d['top1'], d['fault_cases'])}** of fault cases and in the top 3 in **{pct(d['top3'], d['fault_cases'])}**. "
         f"The loudest-alert baseline managed {pct(loud['top1'], loud['fault_cases'])} and random {pct(rnd['top1'], rnd['fault_cases'])}.",
         f"- **Database evidence matters:** on database faults, method D found the cause in "
         f"{db_d[0]}/{db_d[1]} cases with DB evidence and {db_nodb[0]}/{db_nodb[1]} without it.",
         f"- Method D correctly reported \"no incident\" on {pct(d['normal_ok'], d['normal_cases'])} of normal cases "
         "(the baselines always name a culprit).",
         ]
    if live:
        ld = live["methods"]["D (evidence rules)"]
        L.append(f"- On the **live demo app** ({live['cases']} recorded cases), method D found the injected cause first in "
                 f"**{pct(ld['top1'], ld['fault_cases'])}** of fault runs and called "
                 f"{pct(ld['normal_ok'], ld['normal_cases'])} normal runs normal.")
    L += ["- **Caution:** these are early, optimistic numbers. We built the simulator and the rules ourselves, "
          "and the live set is very small. They show the pipeline works; they are not a final result (see section 7).", "",

          "## 2. What was tested", "",
          "**Pipeline (method D):** anomaly detection (median/MAD, must stay unusual for 3 readings) → telemetry snapshot → "
          "trace attribution (each service's own time vs time waiting on others) → evidence-based ranking with hand-set "
          "rules → ranked causes, fault type, evidence report and a raw score (not calibrated).", "",
          "**Compared with:**",
          "- *D, no DB evidence*: the same method with all database data switched off (`--no-db-evidence`).",
          "- *Loudest alert*: blames the service whose latency or error rate jumped the most.",
          "- *Random*: a random order of candidates (fixed seed per case).", "",
          "**Datasets:**",
          "- *Simulator*: 16 fault kinds in 8 groups × 8 cases + 16 normal cases, with noise, missing data, mild faults "
          "and unrelated changes. Candidates: 5 services + the database.",
          "- *Live demo app*: 5 OpenTelemetry-instrumented services + load generator + PostgreSQL in Docker, observed "
          "with OTel Collector, Prometheus (5 s), Jaeger, Loki and postgres-exporter. A fault lab injects one fault for "
          "120 s and the recorder saves the 2 minutes before plus the fault period.", "",
          "**Measures:** top-1 accuracy (first-ranked cause is a true cause), top-3 accuracy, normal cases reported as "
          "normal, and the fault-type guess. True answers are stored separately from telemetry, SHA-256 hashed, and read "
          "only by the evaluation, never by the diagnosis.", "",

          "## 3. Results on the simulator", ""] + _tables(sim) + ["",
          "**Reading the table:**",
          f"- Method D is far ahead of both baselines (top-1 {pct(d['top1'], d['fault_cases'])} vs "
          f"{pct(loud['top1'], loud['fault_cases'])} and {pct(rnd['top1'], rnd['fault_cases'])}).",
          f"- Without DB evidence, top-1 drops to {pct(nodb['top1'], nodb['fault_cases'])}. Groups that lost cases: "
          + ", ".join(f"{g} ({d['by_group'][g][0]} → {nodb['by_group'][g][0]} of {d['by_group'][g][1]})"
                      for g in sorted(d["by_group"]) if nodb["by_group"][g][0] < d["by_group"][g][0])
          + ". With no database data, the service that *calls* the database is blamed instead.",
          f"- Mild faults are harder: method D's top-1 on mild cases was {pct(d['mild_top1'], d['mild_cases'])}.",
          "- Groups where the loudest alert never ranked the true cause first: "
          + (", ".join(g for g in sorted(loud["by_group"]) if loud["by_group"][g][0] == 0) or "none")
          + ". In these the loudest symptom tends to appear at a caller, not at the cause.", ""]

    L += ["## 4. The database-lock story", "",
          "This is our motivation: when a database table is locked, the service that queries it becomes slow and fails. "
          "Without database evidence that slowness looks like the service's own work.", ""]
    if sim_story:
        L += _story_md("Simulator", sim_story)
    if live_story:
        L += _story_md("Live demo app (real PostgreSQL table lock)", live_story)

    if live:
        L += ["## 5. Results on the live demo app", "", "Per recorded case (✓ = top cause is the true cause; "
              "for the normal run ✓ means \"no incident\" was reported):", ""] + _live_rows(LIVE) + [
              ""] + _tables(live) + [""]

    L += ["## 6. What we learned from the live runs", "",
          "These came up while running the live demo app and changed the prototype. We record them here because they "
          "affect how the numbers should be read.", "",
          "1. **Database monitoring went blind during the lock.** postgres-exporter's per-table queries waited on the "
          "same table lock, every scrape timed out, and all DB stats disappeared exactly when they were needed. "
          "We switched those collectors off. Lesson: the monitoring path can share the failure.",
          "2. **Fast crash loops slip past metric checks.** Docker restarted the crashed service in about 0.5 s, so "
          "no metric stayed unusual for 3 readings; the first diagnosis said \"normal\". Only the logs showed repeated "
          "restarts, so a restart signal from logs was added.",
          "3. **A CPU hog looks like network delay.** The starved process answered late, which made calls into it look "
          "slow on the network. The fault-type rules now check CPU/memory before network.",
          "4. **Some faults leave no logs.** Live runs with zero log lines in their snapshot: "
          + (", ".join(f"{labels.read_label(LIVE, c)['fault_kind']}" for c in case_io.list_cases(LIVE)
                       if not _load(LIVE, c)["logs"]) or "none")
          + ". For these, traces and metrics carried all the evidence.", "",
          "Because fixes 2 and 3 were made after seeing these live cases, the live results above are not an unbiased "
          "test of method D.", "",

          "## 7. Limitations", "",
          "- **Optimistic simulator.** The same team wrote the simulator and the rules, and the rules were adjusted "
          "while looking at the simulator.",
          "- **Hand-set weights.** Method D's evidence weights are first guesses; the raw score is not a probability.",
          "- **Small live set.** One run per fault, only 6 of the 16 fault kinds can be injected live, one service graph.",
          "- **No statistics yet.** No confidence intervals or significance tests, so small differences mean little.",
          "- **Recorder tied to our app.** Service names and metric names are fixed for the demo app.", "",

          "## 8. Next steps (planned, not built)", "",
          "- Testing on the OpenTelemetry Demo (Astronomy Shop), as an independent benchmark.",
          "- Learned ranker (method G) to learn the evidence weights.",
          "- Calibrated confidence and a \"not sure\" answer.",
          "- Comparison with MicroRCA, CIRCA and BARO.",
          "- Statistical tests: Wilson confidence intervals, McNemar test, bootstrap.",
          "- Remaining 10 live faults, safe remediation suggestions, and a React dashboard.", "",

          "## 9. How to reproduce", "", "```bash",
          "make data      # regenerate the 144 simulator cases",
          "make report    # re-run everything and rewrite this REPORT.md",
          "make demo      # evaluation table + database-lock story in the terminal",
          "make up && make fault NAME=db_lock && make diagnose   # a new live case (Docker)",
          "```", ""]
    return "\n".join(L)


def main():
    if not case_io.list_cases(SIM):
        raise SystemExit("No simulator data. Run `make data` first.")
    Path("REPORT.md").write_text(build())
    print("Wrote REPORT.md (all numbers computed just now)")


if __name__ == "__main__":
    main()
