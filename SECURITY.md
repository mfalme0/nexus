# Security Policy

## Supported versions

Only the latest `main` branch is supported. NEXUS is pre-1.0 and has no LTS
promise.

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.**

Use GitHub's private reporting via [Security Advisories][advisories] on this
repository. Include:

- what an attacker can do, and what access they need to do it
- the affected file or route
- a minimal reproduction if you have one

You should get an acknowledgement within 72 hours. Fixes land as a private
advisory, credited to you unless you would rather not be named.

[advisories]: https://github.com/mfalme0/nexus/security/advisories/new

## Threat model

NEXUS runs with access to a real homelab: containers, storage, credentials,
network configuration. The interesting threat is not an outside attacker; it is
**the agent acting beyond what its operator intended.**

### What is defended

| Property | Mechanism | ADR |
| --- | --- | --- |
| The model cannot widen its own authority | Allowlist; deny by default | [ADR-0002](docs/decisions/0002-tool-permission-policy.md) |
| Destructive operations are impossible, not merely discouraged | `FORBIDDEN` evaluated first | [ADR-0002](docs/decisions/0002-tool-permission-policy.md) |
| Risky operations need a human | `REQUIRES_APPROVAL` plus an issued grant | [ADR-0003](docs/decisions/0003-approval-authority.md) |
| A caller cannot approve its own action | Approvals are issued, not asserted | [ADR-0003](docs/decisions/0003-approval-authority.md) |
| Conclusions are traceable to observations | `Evidence` carries status and source | — |
| Secrets are not logged or committed | Environment variables only; `SecretStr` | — |

### What is NOT yet defended

Stated plainly, because an incomplete threat model is worse than none:

- **No authentication or authorization on the HTTP API.** Anyone who can reach
  `/api/v1` can read host inventory. This is intended for a homelab reachable only
  from localhost, and it is *not* safe to expose to a network. Authentication is
  not yet implemented.
- **No transport security.** Run behind a reverse proxy if it leaves localhost.
- **No sandbox enforcement.** The Docker Compose sandbox is a convenience for
  testing. It is not a security boundary, and Phase 3 permission classes are not
  bypassed by anything running inside it.
- **`READ_ONLY` tools can still be used to enumerate.** Full inventory of disks,
  memory, and host identity is available to any caller. That is the point of the
  endpoint, and it is why it should not be exposed.
- **Approval store is process-local.** Does not work across multiple workers yet.

## Responsible disclosure

We ask for 90 days before public disclosure. We will not pursue legal action over
good-faith research that respects homelab privacy and does not degrade the service
for others.