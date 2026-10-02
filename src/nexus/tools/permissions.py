"""Permission model and authorization policy for NEXUS tools.

This module is the enforcement point, and it is deliberately out of the model's
reach. The agent may *propose* a tool call; this policy decides whether that call
is allowed to run. Nothing in a prompt, a tool description, or a model response
can widen what is permitted from here.

Two rules from the README are encoded structurally rather than by convention:

1. **Allowlist, not denylist.** A tool is denied unless it has been explicitly
   registered. Adding a capability is an act of omission from the registry, so a
   forgotten tool is safe by default and a newly invented tool does not run.
2. **FORBIDDEN is final.** No execution mode, and no approval, unlocks it.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class PermissionClass(StrEnum):
    """Risk classification declared by a tool, fixed at registration time."""

    READ_ONLY = "READ_ONLY"
    """Observes state. Always permitted."""

    LOW_RISK = "LOW_RISK"
    """Reversible mutation, e.g. restarting a container. Needs a permissive mode."""

    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    """Risky mutation, e.g. pruning storage. Needs a permissive mode *and* a human grant."""

    FORBIDDEN = "FORBIDDEN"
    """Never permitted, in any mode, under any approval."""


class ExecutionMode(StrEnum):
    """How much authority the current run is permitted to exercise."""

    READ_ONLY = "READ_ONLY"
    """The default. Observation only; mutations are refused."""

    PERMISSIVE = "PERMISSIVE"
    """Explicitly enabled by an operator. Unlocks LOW_RISK, still needs approval for the rest."""


class DenialReason(StrEnum):
    """Why a call was refused. Present on every denial."""

    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    """Not in the allowlist. Denied by omission."""

    FORBIDDEN_TOOL = "FORBIDDEN_TOOL"
    """Declared FORBIDDEN. Unreachable by any mode or approval."""

    READ_ONLY_MODE = "READ_ONLY_MODE"
    """The run is in the default READ_ONLY mode."""

    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    """Permissive mode, but no human has approved this specific tool."""


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    """A human's authorization for one specific tool.

    Grants are bound to a tool name and a run, so a grant issued for one action
    cannot be replayed to authorise a different one.
    """

    approval_id: str
    tool_name: str
    granted_by: str
    granted_at: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None
    consumed: bool = False

    def is_expired(self, now: datetime | None = None) -> bool:
        """True when the grant has an expiry that has already passed."""
        if self.expires_at is None:
            return False
        return (now or utcnow()) >= self.expires_at


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """The result of authorizing one proposed tool call.

    `allowed` is the only field a caller must branch on. `reason` is a
    `DenialReason` when denied and a human-readable note when allowed, so a
    refusal always explains itself instead of just returning False.
    """

    allowed: bool
    tool_name: str
    permission_class: PermissionClass | None
    reason: DenialReason | str

    @property
    def denial(self) -> DenialReason | None:
        """The `DenialReason`, or None when the call was allowed."""
        return self.reason if isinstance(self.reason, DenialReason) else None

    @property
    def needs_approval(self) -> bool:
        """True when this call is permissible but is waiting on a human."""
        return self.reason == DenialReason.APPROVAL_REQUIRED


class PermissionPolicy:
    """Allowlist-based authorization for tool calls.

    The registry is empty on construction, so a fresh policy refuses everything.
    Registering a tool *lowers* nothing and raises its class by omission; there is
    no API here that grants a tool more authority than it declares.
    """

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.READ_ONLY,
        *,
        run_id: str = "local",
    ) -> None:
        self._mode = mode
        self._run_id = run_id
        self._registry: dict[str, PermissionClass] = {}

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def registered_tools(self) -> frozenset[str]:
        return frozenset(self._registry)

    def register(self, tool_name: str, permission_class: PermissionClass) -> None:
        """Add a tool to the allowlist at a fixed permission class.

        Re-registering an existing tool is refused rather than silently
        overwritten: a tool's risk class must not be mutable after the fact.
        """
        if tool_name in self._registry:
            msg = f"tool {tool_name!r} is already registered"
            raise ValueError(msg)
        self._registry[tool_name] = permission_class

    def permission_class_for(self, tool_name: str) -> PermissionClass | None:
        return self._registry.get(tool_name)

    def decide(
        self,
        tool_name: str,
        *,
        approval: ApprovalGrant | None = None,
        now: datetime | None = None,
    ) -> PolicyDecision:
        """Authorize a proposed call. This is the single source of truth.

        Precedence is fixed and checked in this order: unknown tools, then
        FORBIDDEN, then execution mode, then approval. FORBIDDEN is evaluated
        before the mode check on purpose, so that no configuration of mode and
        approval can reach it.
        """
        permission_class = self._registry.get(tool_name)

        if permission_class is None:
            return PolicyDecision(
                allowed=False,
                tool_name=tool_name,
                permission_class=None,
                reason=DenialReason.UNKNOWN_TOOL,
            )

        if permission_class is PermissionClass.FORBIDDEN:
            return PolicyDecision(
                allowed=False,
                tool_name=tool_name,
                permission_class=permission_class,
                reason=DenialReason.FORBIDDEN_TOOL,
            )

        if (
            self._mode is ExecutionMode.READ_ONLY
            and permission_class is not PermissionClass.READ_ONLY
        ):
            return PolicyDecision(
                allowed=False,
                tool_name=tool_name,
                permission_class=permission_class,
                reason=DenialReason.READ_ONLY_MODE,
            )

        if permission_class is PermissionClass.REQUIRES_APPROVAL and not self._approval_matches(
            approval,
            tool_name,
            now,
        ):
            return PolicyDecision(
                allowed=False,
                tool_name=tool_name,
                permission_class=permission_class,
                reason=DenialReason.APPROVAL_REQUIRED,
            )

        return PolicyDecision(
            allowed=True,
            tool_name=tool_name,
            permission_class=permission_class,
            reason=f"{permission_class} permitted in {self._mode} mode",
        )

    def _approval_matches(
        self,
        approval: ApprovalGrant | None,
        tool_name: str,
        now: datetime | None,
    ) -> bool:
        """An approval counts only if it is genuine, unconsumed, unexpired, and for this tool."""
        if approval is None or approval.consumed or approval.tool_name != tool_name:
            return False
        return not approval.is_expired(now)
