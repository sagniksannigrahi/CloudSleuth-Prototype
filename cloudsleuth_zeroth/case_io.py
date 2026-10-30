"""Reading and writing case TELEMETRY files.

A dataset folder looks like this:

    data/<dataset>/telemetry/<case_id>.json   <- what the diagnosis may read
    data/<dataset>/labels/<case_id>.json      <- true answer (separate, see labels.py)
    data/<dataset>/labels/SHA256SUMS          <- hash of every label file

Telemetry file fields: case_id, source, interval_s, services, database, edges,
metrics, db, traces, logs, changes. No field says what the fault was.
"""

import json
from pathlib import Path


def telemetry_dir(dataset_dir):
    return Path(dataset_dir) / "telemetry"


def save_telemetry(dataset_dir, telemetry):
    folder = telemetry_dir(dataset_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{telemetry['case_id']}.json"
    path.write_text(json.dumps(telemetry, separators=(",", ":")))
    return path


def load_telemetry(path):
    return json.loads(Path(path).read_text())


def list_cases(dataset_dir):
    """Case ids in a dataset, sorted by name."""
    folder = telemetry_dir(dataset_dir)
    if not folder.exists():
        return []
    return sorted(p.stem for p in folder.glob("*.json"))


def telemetry_path(dataset_dir, case_id):
    return telemetry_dir(dataset_dir) / f"{case_id}.json"


def latest_case(dataset_dir):
    """Most recently written case in a dataset (used after a live fault)."""
    files = list(telemetry_dir(dataset_dir).glob("*.json"))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None
