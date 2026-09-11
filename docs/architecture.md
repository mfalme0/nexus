# NEXUS Architecture

## Overview

NEXUS is an AI-native SRE/operations agent for a personal homelab. It discovers
infrastructure from real observations, investigates incidents through typed
tools, forms evidence-grounded hypotheses, and executes safe remediation behind
an explicit approval system.

The defining constraint is **safety**: the LLM must never have unrestricted
access to the homelab. All authorization lives outside the LLM.

## Layered architecture

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

Layers communicate across well-defined typed boundaries. Modules are organised as:

```
src/nexus/
├── api/          # FastAPI routes (thin)
├── agent/        # LangGraph orchestration
├── tools/        # typed infrastructure tools + permission policy
├── security/     # auth, authorization, approval
├── services/     # domain services (discovery, context, evaluation)
├── db/           # SQLAlchemy models, engine, sessions
├── eval/         # evaluation framework + scenarios
├── config.py     # pydantic-settings configuration
├── logging.py    # structlog configuration
└── main.py       # application factory
```

## Data flow for an incident

1. User submits `"Immich is down."` via API or CLI.
2. API creates an `Incident` and calls the LangGraph agent.
3. The agent **classifies** the incident and the **context engine** selects
   the minimal relevant slice of the knowledge graph (Immich, its host, its
   PostgreSQL/Redis dependencies, recent changes, recent incidents).
4. The agent calls typed **tools** to gather evidence. Every tool call is
   logged to `audit_logs` and `tool_calls` with its permission level.
5. The agent forms **hypotheses** and tests them against evidence. The graph
   loops back to "gather more evidence" when evidence is insufficient.
6. On root cause, the agent proposes remediation. If the action is
   `REQUIRES_APPROVAL`, an `Approval` row is created; nothing executes until
   a human approves.
7. After execution, the agent **verifies** the remediation restored service.
8. State, trace, and outcome are persisted for observability and evaluation.

## Persistence

PostgreSQL is the source of truth (see `src/nexus/db/models.py`), managed by
Alembic migrations. Redis is used for queueing/state checkpointing where
needed. SQLite is not used for the final architecture.

## Key design decisions

- **Read-only by default.** Until the permission system is explicitly enabled,
  every tool is `READ_ONLY`.
- **Allowlist, not denylist.** There is no arbitrary shell execution. Every
  tool is a typed Python function guarded by a permission class.
- **Confidence from evidence, not vibes.** Confidence is derived from the
  volume of independent observations, contradictions, and required-evidence
  coverage — never invented by the LLM.
- **Explainability over autonomy.** Reasoning summaries and evidence are
  displayed; hidden chain-of-thought is never exposed.

See `docs/decisions/` for Architecture Decision Records.