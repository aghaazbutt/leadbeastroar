.PHONY: help install fmt lint type test up down logs shell migrate revision seed smoke

help:
	@echo "LeadBeast — common commands"
	@echo "  make install      install deps into a local .venv"
	@echo "  make up           docker compose up -d"
	@echo "  make down         docker compose down"
	@echo "  make logs         tail app + worker logs"
	@echo "  make migrate      run alembic upgrade head"
	@echo "  make revision m=msg  create a new alembic revision"
	@echo "  make seed         load seed/businesses.csv"
	@echo "  make smoke        run end-to-end smoke test"
	@echo "  make fmt          ruff format"
	@echo "  make lint         ruff check"
	@echo "  make type         mypy --strict"
	@echo "  make test         pytest"

install:
	python -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f app worker

shell:
	docker compose exec app bash

migrate:
	docker compose exec app alembic upgrade head

revision:
	docker compose exec app alembic revision --autogenerate -m "$(m)"

seed:
	docker compose exec app lb ingest csv seeds/businesses.csv --campaign "Demo Visibility Gap"

smoke:
	docker compose exec app pytest tests/test_smoke.py -v

fmt:
	ruff format src tests

lint:
	ruff check src tests

type:
	mypy src

test:
	pytest
