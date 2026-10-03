# Contributing to NEXUS

Thanks for looking. This project has one rule that overrides most others:

> **Never claim more than you can prove.**

The README puts it as *"NEXUS must never confuse sounding confident with being
correct."* That rule applies to the code, to the tests, and to this repository's
own documentation.

## Honesty rules for contributions

- A feature is `REAL`, `SIMULATED`, `MOCK`, or `NOT IMPLEMENTED`. Say which.
- If you cannot verify it, say so in the PR description rather than implying it works.
- Do not add a command that runs and reports nothing. If evaluation does not exist
  yet, there should be no `make eval`. See [#1][issue-1] for that exact mistake, and
  the tests that now prevent it.
- Do not mark a checkbox done because code exists. Mark it done when it is tested
  and running.

[issue-1]: https://github.com/mfalme0/nexus/issues/1

## Setup

```bash
git clone https://github.com/mfalme0/nexus.git
cd nexus
docker compose up -d
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
```

## Quality gates

All four must pass before you open a PR. CI runs the same three:

```bash
make lint        # ruff check
make typecheck   # mypy --strict
make test        # pytest
```

Notes that will save you time:

- `mypy` runs in `strict` mode. Untyped defs and implicit `Any` are rejected.
- `ruff` includes `S` (bandit), so `assert` is disallowed in `src/`.
- Platform-specific calls need care. `os.getloadavg` exists on Linux and not on
  Windows; CI runs Linux but contributors may not. Look it up with `getattr`.
- Tests must pass on Linux **and** Windows. If a probe genuinely cannot run on one
  platform, derive the expectation instead of hard-coding it. See `PLATFORM_GAPS`
  in `tests/test_discovery.py`.

## Testing expectations

- New behaviour needs a test that fails without it.
- Safety properties need tests that are adversarial: assert the handler did **not**
  run, not only that the call was refused.
- Prefer real sources over mocks. `tmp_path` and a synthetic `/proc/meminfo` are
  usually enough, and they test more than a mock does.

## Adding a tool

Three steps, in this order:

1. Declare it in `nexus/tools/`. Pick the **lowest** permission class that is
   honest. If you are unsure, use `REQUIRES_APPROVAL` and say why in the PR.
2. Register it explicitly. Omission from the registry is what denies it.
3. Add tests for the denied path as well as the allowed path.

Read [ADR-0002](docs/decisions/0002-tool-permission-policy.md) first. If a tool
needs to be added to the allowlist temporarily to make your test pass, that is a
signal the design needs revisiting, not a step.

## Pull requests

- One logical change per PR. Separate refactors from behaviour changes.
- Describe what you verified, not just what you changed.
- Reference the issue it closes.
- Expect to be asked for evidence. "Tests pass" is a claim; `pytest -q` output is
  evidence.

## Good first issues

Issues labelled `good first issue` are scoped to be self-contained. Comment before
you start so two people do not do the same work.

## Code of conduct

Be decent. Review the work, not the person. Assume the other person is competent and
missing context rather than incompetent and trying to be clever.