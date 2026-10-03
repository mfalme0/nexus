# ADR-0003: Approvals must be issued, not asserted

- **Status:** accepted
- **Date:** 2026-10-03

## Context

ADR-0002 established that the policy decides whether a call may run. This ADR
covers a narrower and easily-missed question: when a policy decision says
`REQUIRES_APPROVAL`, what counts as proof that a human approved?

This was not hypothetical. The first implementation of
`POST /api/v1/tools/{tool_name}` built an `ApprovalGrant` straight from an
`approval_id` in the request body:

```python
approval = ApprovalGrant(approval_id=payload.approval_id, tool_name=tool_name, granted_by="api")
```

That makes the approval gate decorative. Any caller could unlock a destructive
tool by inventing an identifier, and the test that was supposed to prove otherwise
passed — because it asserted the behaviour the code already had.

## Decision

Issuing an approval and referencing an approval are separate operations, and only
one of them is reachable from outside the process. `nexus/security/approvals.py`
makes that structural:

- `ApprovalStore.issue()` records a grant. Called only by operator-facing approval
  code.
- `ApprovalStore.resolve(approval_id)` returns a grant only if one was genuinely
  issued earlier. An unknown id resolves to `None`, which the policy treats as no
  approval at all.

Two properties fall out of the data model rather than from discipline:

- **An approval is bound to one tool.** A grant names its `tool_name`; a grant for
  `host.memory` does not unlock `docker.prune_cache`.
- **An approval is not standing permission.** Grants expire, and are marked
  consumed once used.

Because the store starts empty and nothing in the HTTP layer can populate it, every
`REQUIRES_APPROVAL` tool currently reports `needs_approval`. That is the correct
behaviour today: Phase 8 owns the actual approval flow.

## Consequences

- + A caller cannot approve its own action, so the gate is a real gate.
- + The empty-store default fails safe: no approval flow means no approvals.
- + Approval is auditable, with `granted_by` on the grant.
- - An approval is single-use and expires. An operator approving "prune the build
  cache" means that action, not that category of action, which is more clicks than
  some workflows want.
- - The store is process-local, so a multi-worker deployment would need shared
  storage before approvals work across workers. Not yet a problem, but it is the
  reason this is recorded now rather than left to Phase 8.