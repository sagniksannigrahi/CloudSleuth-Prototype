# CloudSleuth-Zeroth-Prototype
# All paths are relative, so this works even though "VS Projects" has a space.

PYTHON  ?= python3
VENV    := .venv
VPY     := $(VENV)/bin/python
COMPOSE := docker compose -f "demo_app/docker-compose.yml"
SIM     := data/simulator
LIVE    := data/demo_app
NAME    ?= db_lock
DURATION ?= 120

.PHONY: help check-python data eval story demo venv test viewer up down fault faults diagnose diagnose-nodb live-eval ps logs clean

help:
	@echo "CloudSleuth-Zeroth-Prototype"
	@echo ""
	@echo "Offline demo (no Docker, no internet, no installs):"
	@echo "  make demo           generate simulator data, print the evaluation table, run the DB-lock story"
	@echo "  make data | eval | story   the three steps of 'make demo' on their own"
	@echo ""
	@echo "Viewer and tests (need a one-time pip install into .venv):"
	@echo "  make test           run the pytest tests"
	@echo "  make viewer         web page at http://localhost:8000"
	@echo ""
	@echo "Live demo app (Docker):"
	@echo "  make up             start 6 services + Postgres + OTel Collector, Prometheus, Jaeger, Loki"
	@echo "  make fault NAME=db_lock [DURATION=120]   inject a fault, record a snapshot, save the true answer"
	@echo "  make faults         list the live faults"
	@echo "  make diagnose       diagnose the newest recorded live case (diagnose-nodb: without DB evidence)"
	@echo "  make down           stop everything"

check-python:
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ needed, found ' + sys.version.split()[0]"

data: check-python
	$(PYTHON) -m cloudsleuth_zeroth.simulator.generate --out "$(SIM)"

eval: check-python
	$(PYTHON) -m cloudsleuth_zeroth.evaluation.evaluate "$(SIM)" "$(LIVE)"

story: check-python
	$(PYTHON) -m cloudsleuth_zeroth.evaluation.story --dataset "$(SIM)"

demo: data
	@echo ""
	@echo "================ Evaluation (all numbers computed now) ================"
	@$(MAKE) --no-print-directory eval
	@echo "================ Database-lock story ================"
	@$(MAKE) --no-print-directory story

$(VPY):
	$(PYTHON) -m venv "$(VENV)"
	"$(VPY)" -m pip install -q --upgrade pip
	"$(VPY)" -m pip install -q -r requirements-dev.txt

venv: $(VPY)

test: $(VPY)
	"$(VPY)" -m pytest -q

viewer: $(VPY)
	@test -d "$(SIM)/telemetry" || $(MAKE) --no-print-directory data
	"$(VPY)" -m uvicorn cloudsleuth_zeroth.viewer.app:app --port 8000

up:
	$(COMPOSE) up -d --build
	@echo "Jaeger: http://localhost:16686   Prometheus: http://localhost:9090   Gateway: http://localhost:8080"
	@echo "Wait ~2 minutes for normal traffic to build up before injecting a fault."

down:
	$(COMPOSE) down -v

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs --tail 30

faults:
	$(PYTHON) -m faultlab.fault_lab list

fault: check-python
	$(PYTHON) -m faultlab.fault_lab inject $(NAME) --duration $(DURATION)

diagnose: check-python
	$(PYTHON) -m cloudsleuth_zeroth.core.diagnose --latest "$(LIVE)"

diagnose-nodb: check-python
	$(PYTHON) -m cloudsleuth_zeroth.core.diagnose --latest "$(LIVE)" --no-db-evidence

live-eval: check-python
	$(PYTHON) -m cloudsleuth_zeroth.evaluation.evaluate "$(LIVE)"

clean:
	rm -rf "$(SIM)" results .pytest_cache
