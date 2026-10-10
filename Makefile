PY ?= .venv/bin/python
COMPOSE ?= docker compose

.PHONY: help install up down logs test lint fmt typecheck backtest backtest-official validate-cases seed migrate ci

help:
	@grep -E '^[a-zA-Z_-]+:' Makefile | cut -d: -f1

install:  ## create venv with Python 3.11 and install dev deps
	uv venv -p 3.11 .venv && uv pip install -p $(PY) -r requirements-dev.txt

up:  ## start api, postgres, redis, scheduler, dashboard
	$(COMPOSE) up -d --build
	@echo "API:       http://localhost:8000/docs"
	@echo "Dashboard: http://localhost:8501"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

test:
	$(PY) -m pytest --cov=app/detection --cov=app/features --cov=app/evaluation \
		--cov-report=term-missing --cov-fail-under=80

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

typecheck:
	$(PY) -m mypy app && $(PY) -m mypy dashboard/app.py

ci: lint typecheck test

migrate:
	$(PY) -m alembic upgrade head

seed:  ## load synthetic demo data + score it (needs DATABASE_URL)
	$(PY) -m app.cli seed-demo

backtest:  ## dry-run backtest on synthetic SYNTH_ fixtures
	$(PY) -m app.cli backtest --source synthetic --mode dry-run

backtest-official:  ## official backtest on verified SEBI cases loaded in the DB
	$(PY) -m app.cli backtest --source db --mode official

validate-cases:  ## check data/benchmark/cases_template.csv is acceptable
	$(PY) -m app.cli validate-cases
