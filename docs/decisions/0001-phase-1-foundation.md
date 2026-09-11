# ADR-0001: Phase 1 foundation

- **Status:** accepted
- **Date:** 2026-09-11

## Context

NEXUS requires a reproducible, testable foundation before any agent,
discovery, or tooling is built. Phase 1 establishes the skeleton: API, data
layer, infrastructure services, configuration, logging, health, CI, and tests.

## Decision

- Python 3.12+ with `src/` layout and `pyproject.toml` as the single source of
  truth for project metadata and tool configuration (ruff, mypy, pytest).
- FastAPI with an application factory (`create_app`) to keep test/settings
  isolation clean.
- SQLAlchemy 2.0 async (asyncpg via `postgresql+asyncpg://`) with Alembic
  migrations as the schema source of truth.
- Redis via `redis` client library (connection later).
- structlog with console rendering in development and JSON in production.
- pydantic-settings for configuration, environment-driven.
- The application must boot even when PostgreSQL is down; `/health` reports
  `degraded` rather than the app crashing.
- CI (GitHub Actions) runs ruff, mypy, and pytest against real PostgreSQL and
  Redis service containers.

## Consequences

- + Clean, testable, portable foundation.
- + Dev bootstrap with `docker compose up` + `pip install -e ".[dev]"`.
- - Additional async complexity in Alembic `env.py`.
- - dev/test environments currently converge schema via `create_all`; the
  authoritative path is `alembic upgrade head`. This will be reconciled when
  schema evolution matters (Phase 2+).