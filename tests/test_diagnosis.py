from cloudsleuth_zeroth import case_io, labels
from cloudsleuth_zeroth.core.diagnose import diagnose
from cloudsleuth_zeroth.evaluation.story import find_db_lock_case


def load(ds, case):
    return case_io.load_telemetry(case_io.telemetry_path(ds, case))


def test_db_lock_story(small_dataset):
    """Without DB evidence the DB caller is blamed; with it, the database."""
    case = find_db_lock_case(small_dataset)
    tele = load(small_dataset, case)
    caller = labels.read_label(small_dataset, case)["details"]["caller"]
    off = diagnose(tele, use_db=False)
    on = diagnose(tele, use_db=True)
    assert off["top_cause"] == caller
    assert on["top_cause"] == "postgres"
    assert on["fault_type"] == "db_lock"
    assert on["evidence_report"]["support"]                 # evidence is listed


def test_output_has_ranking_report_and_uncalibrated_score(small_dataset):
    case = find_db_lock_case(small_dataset)
    r = diagnose(load(small_dataset, case))
    assert len(r["ranking"]) == 6                            # 5 services + database
    assert "contradict" in r["evidence_report"]
    assert "NOT calibrated" in r["confidence_note"]


def test_normal_case_is_called_normal(small_dataset):
    normal = [c for c in case_io.list_cases(small_dataset)
              if labels.read_label(small_dataset, c)["fault_kind"] == "normal"]
    assert all(not diagnose(load(small_dataset, c))["incident"] for c in normal)


def test_baselines_return_a_full_ranking(small_dataset):
    case = case_io.list_cases(small_dataset)[0]
    tele = load(small_dataset, case)
    assert len(diagnose(tele, method="loudest")["ranking"]) == 5
    assert len(diagnose(tele, method="random")["ranking"]) == 6
