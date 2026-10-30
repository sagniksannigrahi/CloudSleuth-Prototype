import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cloudsleuth_zeroth.viewer import app as viewer  # noqa: E402


def test_viewer_lists_and_diagnoses(small_dataset, monkeypatch):
    monkeypatch.setattr(viewer, "DATASETS", {"simulator": small_dataset})
    client = TestClient(viewer.app)
    page = client.get("/")
    assert "CloudSleuth-Zeroth-Prototype" in page.text
    cases = client.get("/api/cases").json()
    assert cases["simulator"]
    r = client.get("/api/diagnose", params={"dataset": "simulator", "case": cases["simulator"][0]}).json()
    assert "ranking" in r
