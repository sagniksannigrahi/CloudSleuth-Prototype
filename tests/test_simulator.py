import json

from cloudsleuth_zeroth import case_io, labels
from cloudsleuth_zeroth.faults import FAULT_KINDS, GROUPS


def test_catalogue_has_16_kinds_in_8_groups():
    assert len(FAULT_KINDS) == 16
    assert len(GROUPS) == 8


def test_dataset_counts_and_separate_labels(small_dataset):
    cases = case_io.list_cases(small_dataset)
    assert len(cases) == 16 * 2 + 2
    kinds = [labels.read_label(small_dataset, c)["fault_kind"] for c in cases]
    assert kinds.count("normal") == 2
    assert set(kinds) - {"normal"} == set(FAULT_KINDS)


def test_telemetry_has_no_answer_in_it(small_dataset):
    for c in case_io.list_cases(small_dataset):
        text = case_io.telemetry_path(small_dataset, c).read_text()
        tele = json.loads(text)
        assert "root_causes" not in tele and "fault_kind" not in tele
        assert not any(k in text for k in FAULT_KINDS)


def test_label_hash_detects_tampering(small_dataset, tmp_path):
    import shutil
    import pytest
    copy = tmp_path / "copy"
    shutil.copytree(small_dataset, copy)
    case = case_io.list_cases(copy)[0]
    path = labels.labels_dir(copy) / f"{case}.json"
    path.write_text(path.read_text().replace("simulator", "changed"))
    with pytest.raises(ValueError):
        labels.read_label(copy, case)
