"""Small evaluation: run method D and the two baselines on every case.

top-1 accuracy: the first-ranked cause is a true root cause
top-3 accuracy: a true root cause is somewhere in the first three
(For the 'multiple' group, finding EITHER of the two true causes counts.)

Labels are read here (and only here) to score the results, and every label
file is checked against its SHA-256 hash first. All numbers printed are
computed from this run; nothing is hard-coded.

Run:  python -m cloudsleuth_zeroth.evaluation.evaluate data/simulator data/demo_app
"""

import argparse
import json
import time
from pathlib import Path

from .. import case_io, labels
from ..core.diagnose import diagnose
from ..faults import GROUPS

METHODS = [
    ("D (evidence rules)", {"method": "D", "use_db": True}),
    ("D, no DB evidence", {"method": "D", "use_db": False}),
    ("Loudest alert", {"method": "loudest", "use_db": True}),
    ("Random", {"method": "random", "use_db": True}),
]


def score_dataset(dataset_dir):
    """Run every method on every case. Returns a dict of counts."""
    cases = case_io.list_cases(dataset_dir)
    out = {"dataset": str(dataset_dir), "cases": len(cases), "methods": {}}
    for name, cfg in METHODS:
        m = {"fault_cases": 0, "top1": 0, "top3": 0, "normal_cases": 0, "normal_ok": 0,
             "by_group": {}, "type_cases": 0, "type_exact": 0, "type_group": 0,
             "mild_cases": 0, "mild_top1": 0}
        for case_id in cases:
            label = labels.read_label(dataset_dir, case_id)        # hash-checked
            tele = case_io.load_telemetry(case_io.telemetry_path(dataset_dir, case_id))
            r = diagnose(tele, use_db=cfg["use_db"], method=cfg["method"])
            names = [x["node"] for x in r["ranking"]] if r["incident"] else []
            truth = set(label["root_causes"])
            if not truth:                                             # a normal case
                m["normal_cases"] += 1
                m["normal_ok"] += int(not r["incident"])
                continue
            hit1 = bool(names[:1]) and names[0] in truth
            hit3 = bool(truth & set(names[:3]))
            m["fault_cases"] += 1
            m["top1"] += hit1
            m["top3"] += hit3
            g = m["by_group"].setdefault(label["fault_group"], [0, 0])
            g[0] += hit1
            g[1] += 1
            if label.get("severity") == "mild":
                m["mild_cases"] += 1
                m["mild_top1"] += hit1
            if cfg["method"] == "D" and label["fault_group"] != "multiple":   # fault-type guess
                m["type_cases"] += 1
                if r["incident"]:
                    m["type_exact"] += int(r["fault_type"] == label["fault_kind"])
                    m["type_group"] += int(r["fault_group"] == label["fault_group"])
        out["methods"][name] = m
    return out


def pct(a, b):
    return f"{a}/{b} = {100 * a / b:5.1f}%" if b else "n/a"


def as_table(res):
    lines = [f"Dataset: {res['dataset']}  ({res['cases']} cases)", "",
             f"| {'Method':<20} | {'Top-1 accuracy':<18} | {'Top-3 accuracy':<18} | {'Normal cases called normal':<26} |",
             f"|{'-' * 22}|{'-' * 20}|{'-' * 20}|{'-' * 28}|"]
    for name, m in res["methods"].items():
        lines.append(f"| {name:<20} | {pct(m['top1'], m['fault_cases']):<18} | "
                     f"{pct(m['top3'], m['fault_cases']):<18} | {pct(m['normal_ok'], m['normal_cases']):<26} |")
    groups = [g for g in GROUPS if any(g in m["by_group"] for m in res["methods"].values())]
    if groups:
        lines += ["", "Top-1 accuracy per fault group (hits / cases):", "",
                  "| Method               | " + " | ".join(f"{g:<12}" for g in groups) + " |",
                  "|" + "-" * 22 + "|" + "|".join("-" * 14 for _ in groups) + "|"]
        for name, m in res["methods"].items():
            cells = [f"{m['by_group'][g][0]}/{m['by_group'][g][1]}" if g in m["by_group"] else "-" for g in groups]
            lines.append(f"| {name:<20} | " + " | ".join(f"{c:<12}" for c in cells) + " |")
    d = res["methods"]["D (evidence rules)"]
    lines += ["", f"Method D fault-type guess (single-fault cases): exact kind {pct(d['type_exact'], d['type_cases'])}, "
                  f"right group {pct(d['type_group'], d['type_cases'])}",
              f"Method D top-1 on MILD faults only: {pct(d['mild_top1'], d['mild_cases'])}",
              "Confidence: method D gives a raw score only; it is NOT calibrated yet (planned)."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Evaluate method D and baselines.")
    ap.add_argument("datasets", nargs="+")
    ap.add_argument("--save", default="results", help="folder for the result files")
    a = ap.parse_args()
    Path(a.save).mkdir(exist_ok=True)
    for ds in a.datasets:
        if not case_io.list_cases(ds):
            print(f"(skipping {ds}: no cases recorded yet)\n")
            continue
        t0 = time.time()
        res = score_dataset(ds)
        table = as_table(res)
        print(table)
        print(f"(computed just now in {time.time() - t0:.1f} s)\n")
        name = Path(ds).name
        Path(a.save, f"evaluation_{name}.md").write_text(table + "\n")
        Path(a.save, f"evaluation_{name}.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
