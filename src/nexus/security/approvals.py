"""Human approval storage.

Approvals must be *issued by a trusted flow* and merely *referenced* by whoever
performs the action. Conflating the two is how an approval system turns into a
self-approval system: if a caller can name an approval id and have it honoured, the
approval gate protects nothing.

So the two directions are separate here, and only one of them is reachable from
outside the process:

- `issue()` is for operator-facing approval code (Phase 8). Nothing in the HTTP
  layer calls it.
- `resolve()` accepts an id that arrived over the wire and returns a grant only if
  that grant was genuinely issued earlier. An unknown id resolves to `None`, which
  the policy treats as no approval at all.

The store starts empty. Until the approval flow exists, every
`REQUIRES_APPROVAL` tool correctly reports that it is waiting on a human.
"""

from collections.abc import Iterator
from datetime import timedelta

from nexus.tools.permissions import ApprovalGrant, utcnow

DEFAULT_TTL = timedelta(minutes=15)


class ApprovalStore:
    """Process-local registry of issued approvals."""

    def __init__(self) -> None:
        self._grants: dict[str, ApprovalGrant] = {}

    def __len__(self) -> int:
        return len(self._grants)

    def __iter__(self) -> Iterator[ApprovalGrant]:
        return iter(tuple(self._grants.values()))

    def issue(
        self,
        tool_name: str,
        granted_by: str,
        *,
        ttl: timedelta | None = DEFAULT_TTL,
    ) -> ApprovalGrant:
        """Record a human's approval. For internal approval flows only.

        Grants expire by default. An approval to prune storage is consent for one
        action in the next few minutes, not standing permission.
        """
        expiry = utcnow() + ttl if ttl is not None else None
        grant = ApprovalGrant(
            approval_id=f"ap-{len(self._grants) + 1}-{tool_name}",
            tool_name=tool_name,
            granted_by=granted_by,
            expires_at=expiry,
        )
        self._grants[grant.approval_id] = grant
        return grant

    def resolve(self, approval_id: str) -> ApprovalGrant | None:
        """Look up a previously issued grant. Returns None for anything unknown."""
        grant = self._grants.get(approval_id)
        if grant is None or grant.is_expired():
            return None
        return grant

    def consume(self, approval_id: str) -> bool:
        """Mark a grant used. Returns False if it was unknown or already consumed."""
        grant = self._grants.get(approval_id)
        if grant is None or grant.consumed or grant.is_expired():
            return False
        self._grants[approval_id] = ApprovalGrant(
            approval_id=grant.approval_id,
            tool_name=grant.tool_name,
            granted_by=grant.granted_by,
            granted_at=grant.granted_at,
            expires_at=grant.expires_at,
            consumed=True,
        )
        return True

    def revoke(self, approval_id: str) -> bool:
        """Forget a grant. Returns False if it was not present."""
        return self._grants.pop(approval_id, None) is not None
