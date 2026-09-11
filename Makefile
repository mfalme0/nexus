.PHONY: install dev test lint format typecheck eval migrate migrate-up migrate-autogen down sandbox-up sandbox-down compose-up clean

PYTHON ?= python

install:
	pip install -e ".[dev]"
	pre-commit install

dev:
	uvicorn nexus.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -v

test-unit:
	pytest -v -m unit tests

test-integration:
	pytest -v -m integration tests

lint:
	ruff check src tests alembic/env.py

format:
	ruff format src tests
	ruff check --fix src tests

typecheck:
	mypy src

migrate:
	alembic upgrade head

migrate-autogen:
	alembic revision --autogenerate -m "$(msg)"

eval:
	python -m nexus.eval.cli run

compose-up:
	docker compose up -d

compose-down:
	docker compose down

sandbox-up:
	docker compose -f docker-compose.sandbox.yml up -d

sandbox-down:
	docker compose -f docker-compose.sandbox.yml down

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache