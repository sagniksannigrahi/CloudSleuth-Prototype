"""The diagnosis pipeline:

  1 anomaly detection  ->  2 telemetry snapshot  ->  3 trace attribution
  ->  4 evidence-based ranking (method D)  ->  5 output (ranked causes,
  fault type, evidence report, raw score)

This module reads ONLY a telemetry file. It never opens the labels folder.

Run:
  python -m cloudsleuth_zeroth.core.diagnose data/simulator/telemetry/sim-001.json
  python -m cloudsleuth_zeroth.core.diagnose <file> --no-db-evidence
  python -m cloudsleuth_zeroth.core.diagnose --latest data/demo_app
"""

import argparse
import json
import sys

from .. import case_io
from ..faults import group_of
from . import anomaly, attribution, baselines, ranking, report, snapshot

CONFIDENCE_NOTE = "raw score only - NOT calibrated yet (calibration is planned)"


def diagnose(telemetry, use_db=True, method="D"):
    """Diagnose one case. method: 'D', 'loudest' or 'random'."""
    view = snapshot.prepare(telemetry, use_db)
    result = {"case_id": view["case_id"], "source": view["source"], "method": method,
              "use_db_evidence": use_db, "confidence_note": CONFIDENCE_NOTE}

    if method == "loudest":
        return {**result, "incident": True, "ranking": baselines.loudest_alert(view)}
    if method == "random":
        return {**result, "incident": True, "ranking": baselines.random_guess(view)}

    # 1. anomaly detection
    found = anomaly.scan(view)
    result["anomalies"] = [vars(a) for a in found]
    if not found:
        return {**result, "incident": False, "ranking": [],
                "summary": "no persistent anomaly found: looks normal"}

    # 2. telemetry snapshot around the onset
    onset = min(a.onset for a in found)
    snap = snapshot.cut(view, anomaly.baseline_end(view["steps"]), onset)

    # 3. trace attribution (own time vs waiting time)
    attr = attribution.attribute(snap)

    # 4. evidence-based ranking
    ranked, fault_type = ranking.rank(snap, found, attr)

    # 5. output
    top = ranked[0]
    return {**result, "incident": True,
            "onset_s": onset * view["interval_s"],
            "ranking": ranked,
            "top_cause": top["node"],
            "fault_type": fault_type,
            "fault_group": group_of(fault_type),
            "raw_score": top["raw_score"],
            "evidence_report": {"cause": top["node"], "support": top["support"],
                                "contradict": top["contradict"]},
            "attribution": attr}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Diagnose one case (reads telemetry only).")
    ap.add_argument("telemetry", nargs="?", help="path to a telemetry .json file")
    ap.add_argument("--latest", metavar="DATASET_DIR", help="diagnose the newest case in a dataset folder")
    ap.add_argument("--no-db-evidence", action="store_true", help="switch OFF all database data")
    ap.add_argument("--method", default="D", choices=["D", "loudest", "random"])
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = ap.parse_args(argv)
    path = a.telemetry
    if a.latest:
        path = case_io.latest_case(a.latest)
        if path is None:
            sys.exit(f"No cases in {a.latest}/telemetry yet. Inject a fault first (make fault NAME=db_lock).")
    if not path:
        ap.error("give a telemetry file or --latest DATASET_DIR")
    result = diagnose(case_io.load_telemetry(path), use_db=not a.no_db_evidence, method=a.method)
    print(json.dumps(result, indent=2, default=str) if a.json else report.as_text(result))


if __name__ == "__main__":
    main()
