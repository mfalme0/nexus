# NEXUS — Autonomous Homelab Operations Agent

NEXUS is an AI-native SRE/operations agent for a personal homelab. It discovers
infrastructure, investigates incidents, gathers evidence through typed tools,
forms and tests hypotheses, explains root causes, and — only after explicit
approval for risky actions — executes and verifies safe remediation.

**Core principle: NEXUS must never confuse sounding confident with being correct.**

## Architecture

```
                 ┌─────────────────────┐
                 │     Web Console     │
                 │     React/Next.js   │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │      FastAPI        │
                 │        API          │
                 └──────────┬──────────┘
            ┌───────────────┼────────────────┐
            ▼               ▼                ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │ Agent Engine │ │ Infrastructure│ │ Evaluation   │
    │  LangGraph   │ │   Service   │ │   Service    │
    └──────┬───────┘ └──────────────┘ └──────────────┘
           │
           ▼
    ┌──────────────┐
    │ Context Engine│
    └──────┬───────┘
           ▼
      Tools + State + Knowledge
           ▼
        Homelab
```

See [docs/architecture.md](docs/architecture.md) for details.

## Status

Phase 1 (Foundation) in progress: FastAPI, PostgreSQL, Redis, config, logging,
health endpoint, initial tests.

## Development

Requires Python 3.12+, Docker, and Docker Compose.

```bash
# Start PostgreSQL and Redis
docker compose up -d

# Install
pip install -e ".[dev]"

# Run the API
uvicorn nexus.main:app --reload --port 8000

# Tests / lint / types
pytest
ruff check src tests
mypy src
```

See [docs/deployment.md](docs/deployment.md) for deployment details.