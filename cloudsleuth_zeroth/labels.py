"""Ground-truth labels, stored SEPARATELY from telemetry.

Only the simulator / fault lab (which write labels) and the evaluation layer
(which scores results) import this module. The diagnosis core never does;
tests/test_no_label_access.py checks this.

Every label file is hashed with SHA-256 into labels/SHA256SUMS, in the same
format as the `shasum -a 256` tool, so anyone can check that no label was
changed after the run:   cd data/simulator/labels && shasum -a 256 -c SHA256SUMS
"""

import hashlib
import json
from pathlib import Path


def labels_dir(dataset_dir):
    return Path(dataset_dir) / "labels"


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_sums(folder):
    sums = {}
    sums_file = folder / "SHA256SUMS"
    if sums_file.exists():
        for line in sums_file.read_text().splitlines():
            digest, name = line.split("  ", 1)
            sums[name] = digest
    return sums


def _write_sums(folder, sums):
    lines = [f"{digest}  {name}" for name, digest in sorted(sums.items())]
    (folder / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def write_label(dataset_dir, label):
    """Write one label file and record its SHA-256 hash."""
    folder = labels_dir(dataset_dir)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{label['case_id']}.json"
    (folder / name).write_text(json.dumps(label, indent=2, sort_keys=True) + "\n")
    sums = _read_sums(folder)
    sums[name] = sha256_of(folder / name)
    _write_sums(folder, sums)


def read_label(dataset_dir, case_id):
    """Read a label and refuse it if its hash does not match SHA256SUMS."""
    folder = labels_dir(dataset_dir)
    name = f"{case_id}.json"
    expected = _read_sums(folder).get(name)
    if expected is None:
        raise ValueError(f"label {name} has no hash in SHA256SUMS")
    if sha256_of(folder / name) != expected:
        raise ValueError(f"label {name} was modified: SHA-256 does not match")
    return json.loads((folder / name).read_text())
