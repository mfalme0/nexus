# ADR-0002: Tool permissions are an allowlist decided outside the model

- **Status:** accepted
- **Date:** 2026-10-03

## Context

The README commits to two constraints that are easy to state and easy to erode:

- *Allowlist, not denylist.* No arbitrary `bash -c`, `sudo`, or `rm -rf`.
  Every capability is a typed tool with a permission class.
- *Approval before risk.* `REQUIRES_APPROVAL` actions cannot run until a human
  says yes, and *"the authorization layer lives outside the LLM."*

The failure mode this guards against is specific: an agent that is refused by
`sudo`, tries a variant that is not refused, and reports success. Any design where
the model can widen its own authority by choosing a different tool name will
reproduce that.

## Decision

Authorization is a pure function of `(tool_name, execution_mode, approval)`, living
in `nexus/tools/permissions.py`, with three structural properties:

1. **Deny by default.** `PermissionPolicy` starts with an empty registry. A tool is
   denied as `UNKNOWN_TOOL` unless it was explicitly registered. A forgotten tool
   is safe; a tool the model invents does not exist.
2. **`FORBIDDEN` is checked before everything else.** `decide()` evaluates in fixed
   order: unknown, then FORBIDDEN, then mode, then approval. No combination of
   mode and approval can reach a `FORBIDDEN` tool.
3. **Risk class is immutable after registration.** Re-registering a name raises
   rather than overwriting, so a tool's authority cannot be upgraded after the
   fact.

`ToolExecutor` is the only place a handler is invoked, and it authorizes first.
Discovery also goes through it, so discovery is not a side door around the policy.

Denials are typed (`DenialReason`) rather than a bare `False`, so a refusal is
always explainable in an audit log instead of being indistinguishable from a bug.

## Consequences

- + The model cannot escalate its own authority, only request operations an
  operator has already classified.
- + Refusals are auditable and specific.
- + Registering a capability is an explicit act, which makes the tool surface
  reviewable by reading one list.
- - Adding a tool is a two-line change in two places (define, register). Slightly
  more ceremony than a decorator.
- - `LOW_RISK` requires flipping the execution mode, which is a process-level
  decision rather than a per-call one. Revisited when per-call policy scoping
  (Phase 8) lands.
- - Gated tools stay visible in the manifest, including their permission class.
  This is deliberate: telling the model a tool exists and needs approval is more
  useful than letting it discover the gate by being rejected.