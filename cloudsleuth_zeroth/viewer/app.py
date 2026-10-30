"""Simple viewer: one HTML page to pick a case, run the diagnosis, and see
the ranked causes and the evidence report. (The React dashboard is planned.)

Run:  make viewer      then open http://localhost:8000
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .. import case_io, labels
from ..core.diagnose import diagnose

ROOT = Path(__file__).resolve().parents[2]
DATASETS = {"simulator": ROOT / "data" / "simulator", "demo_app": ROOT / "data" / "demo_app"}
PAGE = Path(__file__).with_name("index.html")

app = FastAPI(title="CloudSleuth-Zeroth-Prototype")


def _dataset(name):
    if name not in DATASETS:
        raise HTTPException(404, f"unknown dataset {name}")
    return DATASETS[name]


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE.read_text()


@app.get("/api/cases")
def cases():
    return {name: case_io.list_cases(folder) for name, folder in DATASETS.items()}


@app.get("/api/diagnose")
def run(dataset: str, case: str, no_db: bool = False, method: str = "D"):
    folder = _dataset(dataset)
    if case not in case_io.list_cases(folder):
        raise HTTPException(404, f"unknown case {case}")
    result = diagnose(case_io.load_telemetry(case_io.telemetry_path(folder, case)),
                      use_db=not no_db, method=method)
    result.pop("attribution", None)
    return result


@app.get("/api/truth")
def truth(dataset: str, case: str):
    """The true answer, only shown when the user clicks 'reveal' AFTER diagnosing."""
    return labels.read_label(_dataset(dataset), case)
