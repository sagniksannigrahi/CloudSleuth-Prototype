"""The motivation story: a database lock, diagnosed WITHOUT and WITH database evidence.

  WITHOUT DB evidence, the DB time looks like the calling service's own work,
  so the service that CALLS the database gets blamed (wrong).
  WITH DB evidence, the lock waits and the DB time point at the database (right).

This script lives in the evaluation layer: it uses the labels only to PICK a
database-lock case and to reveal the true answer at the end. The diagnosis
itself is the normal core, which never sees the labels.

Run:  python -m cloudsleuth_zeroth.evaluation.story [--dataset data/simulator] [--case sim-XXX]
"""

import argparse

from .. import case_io, labels
from ..core import report
from ..core.diagnose import diagnose


def find_db_lock_case(dataset_dir):
    """First strong db_lock case where inventory is the service waiting on the lock."""
    fallback = None
    for case_id in case_io.list_cases(dataset_dir):
        lab = labels.read_label(dataset_dir, case_id)
        if lab["fault_kind"] != "db_lock":
            continue
        fallback = fallback or case_id
        details = lab.get("details") or {}
        if details.get("caller") == "inventory" and lab.get("severity") != "mild":
            return case_id
    return fallback


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default="data/simulator")
    ap.add_argument("--case", help="case id (default: a database-lock case)")
    a = ap.parse_args()
    case_id = a.case or find_db_lock_case(a.dataset)
    if not case_id:
        raise SystemExit(f"No database-lock case found in {a.dataset}")
    tele = case_io.load_telemetry(case_io.telemetry_path(a.dataset, case_id))

    print("#" * 72)
    print("# STORY, part 1: database evidence switched OFF  (--no-db-evidence)")
    print("#" * 72)
    off = diagnose(tele, use_db=False)
    print(report.as_text(off))
    print()
    print("#" * 72)
    print("# STORY, part 2: the SAME case, database evidence switched ON")
    print("#" * 72)
    on = diagnose(tele, use_db=True)
    print(report.as_text(on))

    truth = labels.read_label(a.dataset, case_id)       # revealed only after diagnosis
    print()
    print("#" * 72)
    print(f"# True answer (from the hashed label file): {truth['fault_kind']} -> {truth['root_causes']}")
    print(f"#   without DB evidence the top cause was: {off.get('top_cause')}  "
          f"({'right' if off.get('top_cause') in truth['root_causes'] else 'WRONG'})")
    print(f"#   with    DB evidence the top cause was: {on.get('top_cause')}  "
          f"({'right' if on.get('top_cause') in truth['root_causes'] else 'WRONG'})")
    print("#" * 72)


if __name__ == "__main__":
    main()
