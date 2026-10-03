# NEXUS — Autonomous Homelab Operations Agent

**An AI SRE for your homelab that has to show its work.**

NEXUS investigates incidents the way a careful human operator would: it observes
the real infrastructure, collects evidence with typed tools, forms hypotheses,
tests them, and only then explains a root cause. Risky actions need human
approval. Every conclusion must be backed by something it actually observed.

> **Core principle:** NEXUS must never confuse sounding confident with being correct.

When it can't prove something, the correct answer is:

> "I could not verify disk usage because the host did not respond."

...not "Disk usage is normal."

---

## Why this is not another chatbot wrapper

Most "AI ops" demos ask an LLM to guess. NEXUS is built around the opposite
constraint. It embodies four hard rules:

| Rule | What it means in practice |
| --- | --- |
| **Evidence over vibes** | Confidence is derived from observations, contradictions, and required-evidence coverage — never invented by the model. |
| **Allowlist, not denylist** | No arbitrary `bash -c`, `sudo`, or `rm -rf`. Every capability is a typed tool with a permission class. |
| **Approval before risk** | `REQUIRES_APPROVAL` actions cannot run until a human says yes. The authorization layer lives *outside* the LLM. |
| **Explainable, not opaque** | The console shows reasoning summaries and evidence — never hidden chain-of-thought. |

This is the difference between a system that can restart a container and a system
that can show you *why* it was safe to restart, *what evidence* supported it, and
*proof the service recovered*.

---

## What an investigation looks like (target design)

```
You:            "Immich is down."

NEXUS:  classify    → SERVICE_UNAVAILABLE
        context     → Immich, its host, PostgreSQL + Redis deps,
                      recent changes, recent related incidents
        evidence    → container status, recent logs, dependency health,
                      host disk/memory
        hypothesis  → "Immich's container is in a crash loop caused by
                       PostgreSQL refusing connections after disk filled."
        test        → check disk usage + Postgres logs on the same host
        root cause  → storage exhaustion on the host filesystem
        remediation → prune stale Docker build cache (LOW_RISK)
        safety      → disk change → REQUIRES_APPROVAL
        approve     → you click Approve
        execute     → run allowlisted action
        verify      → Immich healthcheck passes, logs stop repeating
        close       → full trace + outcome recorded for evaluation
```

The reasoning graph loops whenever evidence is insufficient — it does not
invent a root cause just to finish.

---

## Project status

NEXUS is built in verifiable phases. **Nothing below is claimed until it is
tested and running.**

### ✅ Phase 1 — Foundation (complete)

Real, working, and verified against live PostgreSQL and Redis:

- FastAPI application factory + `/api/v1/health` with a real database check
- PostgreSQL 16 persistence — full domain schema (hosts, services,
  dependencies, incidents, evidence, agent runs, tool calls, approvals, audit
  logs, evaluations) via SQLAlchemy 2.0 async
- Alembic migrations (async) applied to a live database
- Redis 7 via Docker Compose
- Structured logging (`structlog`), typed config (`pydantic-settings`)
- CLI entrypoint (`nexus`), sandbox compose stack for safe testing
- CI: ruff, mypy (`strict`), pytest against real PG + Redis services
- Graceful degradation: the app boots and reports `degraded` when the DB is down

### ✅ Phase 2 — Infrastructure discovery (complete)

Real, read-only observation of the local host, with honest failure:

- Typed tool layer (`nexus/tools/`) — every capability declares a permission class
- **Allowlist** permission policy (`READ_ONLY` / `LOW_RISK` / `REQUIRES_APPROVAL` /
  `FORBIDDEN`), enforced outside the LLM; a new policy denies everything
- `FORBIDDEN` is evaluated first, so no mode or approval can reach it
- Read-only host probes: disk usage, memory, OS, load average, CPU count
- `Evidence` records carry an explicit `OBSERVED` / `UNAVAILABLE` status, so
  *"I could not verify disk usage because the host did not respond"* is a result
  the system can actually produce
- Inventory endpoints: `GET /api/v1/inventory/host`, `GET /api/v1/tools`,
  `POST /api/v1/tools/{tool_name}`
- Approvals must be **issued**, never asserted — an HTTP caller cannot approve its
  own action (see [ADR-0003](docs/decisions/0003-approval-authority.md))

### 🚧 Roadmap

- [ ] **Phase 3** — Safe remediation actions behind the approval gate
- [ ] **Phase 4** — LangGraph agent (investigate → evidence → diagnose → explain)
- [ ] **Phase 5** — Dynamic context engine
- [ ] **Phase 6** — Evaluation framework (25+ scenarios, regression gates)
- [ ] **Phase 7** — Observability (Langfuse tracing)
- [ ] **Phase 8** — Operator-facing approval flow + audit UI
- [ ] **Phase 9** — Chaos lab (controlled failure scenarios)
- [ ] **Phase 10** — Operations console (React/Next.js)
- [ ] **Phase 11** — Hardening, API authentication, regression testing

> Honest rule of this repo: features are marked `REAL`, `SIMULATED`, `MOCK`,
> or `NOT IMPLEMENTED`. See [docs/architecture.md](docs/architecture.md).

---

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
        │  LangGraph   │ │   Service     │ │   Service    │
        └──────┬───────┘ └──────────────┘ └──────────────┘
               │
               ▼
        ┌──────────────────┐
        │ Context Engine   │
        └────────┬─────────┘
                 │
        ┌────────┼─────────┐
        ▼        ▼         ▼
      Tools    State    Knowledge
        │        │         │
        ▼        ▼         ▼
     Docker   PostgreSQL  Topology
     Linux    Redis       Graph
     Network
     Storage
     Metrics
     Logs
        │
        ▼
   Actual Homelab
```

Clean boundaries between API, agent orchestration, context engineering, tools,
infrastructure state, evaluation, observability, and frontend. No monolith
"main.py" — see [`src/nexus/`](src/nexus/).

---

## Quickstart (what works today)

**Requirements:** Python 3.12+, Docker / Docker Compose.

```bash
git clone https://github.com/mfalme0/nexus.git
cd nexus

# 1. Start PostgreSQL + Redis
docker compose up -d

# 2. Install (editable, with dev tools)
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Apply the schema
alembic upgrade head

# 4. Run the API
uvicorn nexus.main:app --reload --port 8000
```

Then open **http://localhost:8000/docs** for the interactive OpenAPI docs, or:

```bash
curl http://localhost:8000/api/v1/health
# {"status":"healthy","version":"0.1.0","checks":{"database":"healthy"}}
```

### Quality gates

```bash
make test        # pytest
make lint        # ruff
make typecheck   # mypy --strict
```

`make dev`, `make migrate`, and `make sandbox-up` are also available.

The evaluation harness is a Phase 6 deliverable, so there is deliberately no `eval`
target (#1 removed one that pointed at a module that never existed). An `eval`
command that ran and reported nothing would be worse than no command at all.

---

## Safety model

The homelab holds real services and real data, so safety is a hard requirement,
not a feature flag.

- **Default mode is `READ_ONLY`.** No destructive ops, no automatic restarts or
  deletes, no firewall/storage/package changes, no arbitrary shell — until the
  permission system is implemented and explicitly enabled.
- **Tool permission classes:** `READ_ONLY`, `LOW_RISK`, `REQUIRES_APPROVAL`,
  `FORBIDDEN`. The model cannot bypass them; authorization is enforced outside
  the LLM.
- **Early testing runs against a dedicated Docker Compose sandbox**, never the
  production homelab by default.
- **Secrets stay in environment variables**, are never logged, and are never
  committed.

---

## Project layout

```
src/nexus/
├── api/          # FastAPI routes (thin)
├── agent/        # LangGraph orchestration
├── tools/        # typed infrastructure tools + permission policy
├── security/     # auth, authorization, approvals
├── services/     # discovery, context, evaluation services
├── db/           # SQLAlchemy models, engine, sessions
├── config.py     # pydantic-settings configuration
├── logging.py    # structlog configuration
└── main.py       # application factory
alembic/          # database migrations
tests/            # unit + integration tests
docs/             # architecture and decision records
```

---

## Documentation

- [Architecture](docs/architecture.md)
- [ADR-0001: Phase 1 foundation](docs/decisions/0001-phase-1-foundation.md)
- [ADR-0002: Tool permissions are an allowlist decided outside the model](docs/decisions/0002-tool-permission-policy.md)
- [ADR-0003: Approvals must be issued, not asserted](docs/decisions/0003-approval-authority.md)
- [Contributing](CONTRIBUTING.md) — including the honesty rules this repo follows
- [Security policy](SECURITY.md) — threat model, and what is *not* defended yet

More land as each phase completes: agent design, context engineering, tool
security, evaluation, observability, failure analysis, and chaos engineering.

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
Security vulnerabilities should go through private advisory reporting, not a public
issue: see [SECURITY.md](SECURITY.md).

---

## Philosophy

NEXUS is not optimized to look impressive. It is optimized to be **correct,
observable, testable, explainable, recoverable, and safe.**

The impressive part is not that an LLM can restart Docker. It is that NEXUS can
say: *here is what I observed, here is what I believe happened, here is the
evidence, here is what I'm uncertain about, here is the safest available action,
here is why I'm allowed to take it, and here is proof the system recovered.*

## License

MIT
