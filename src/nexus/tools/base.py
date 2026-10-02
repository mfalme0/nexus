"""Typed tool definitions, the registry that allowlists them, and the executor
that enforces the permission policy.

The split matters. A `ToolDefinition` declares *what a tool is* and *how risky it
is*. The `ToolRegistry` decides *whether it may exist*. The `ToolExecutor` is the
only place a handler is ever invoked, and it consults `PermissionPolicy` first.

Handlers are invoked with a single read-only mapping of arguments rather than
keyword arguments. That mirrors how the agent actually emits calls (a JSON object
from the model), and it keeps every handler behind one uniform, validatable shape
instead of inheriting whatever signature a tool happened to be written with.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from nexus.tools.permissions import (
    ApprovalGrant,
    DenialReason,
    PermissionClass,
    PermissionPolicy,
    PolicyDecision,
)

ToolHandler = Callable[[Mapping[str, Any]], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """One capability the agent may propose, and how risky invoking it is."""

    name: str
    description: str
    permission_class: PermissionClass
    handler: ToolHandler
    parameters: Mapping[str, Any] = field(default_factory=dict)
    """JSON Schema for the argument object. Only `properties` and `required` are enforced."""

    @property
    def required_arguments(self) -> tuple[str, ...]:
        required = self.parameters.get("required", [])
        return tuple(str(name) for name in required)

    def validate(self, arguments: Mapping[str, Any]) -> str | None:
        """Return a human-readable problem with `arguments`, or None if they are usable."""
        missing = [name for name in self.required_arguments if name not in arguments]
        if missing:
            return f"missing required argument(s): {', '.join(sorted(missing))}"

        known = set(self.parameters.get("properties", {}))
        unexpected = sorted(set(arguments) - known) if known else []
        if unexpected:
            return f"unknown argument(s): {', '.join(unexpected)}"
        return None

    def manifest_entry(self) -> dict[str, Any]:
        """The description of this tool that is shown to the model.

        The permission class is included rather than hidden. Telling the model
        that a tool exists and needs approval is more useful than letting it
        discover the gate by having calls rejected.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": dict(self.parameters),
            "permission_class": str(self.permission_class),
        }


@dataclass(frozen=True, slots=True)
class ToolResult:
    """The outcome of one attempted tool call, allowed or not."""

    tool_name: str
    ok: bool
    decision: PolicyDecision
    value: Any = None
    error: str | None = None

    @property
    def denied(self) -> bool:
        """True when the policy refused the call, so no handler ran."""
        return not self.ok and self.decision.denial is not None

    @property
    def needs_approval(self) -> bool:
        """True when the call was refused only because it awaits a human grant."""
        return not self.ok and self.decision.needs_approval


class ToolRegistry:
    """Allowlist of tool definitions, paired with the policy that governs them.

    Registration is mirrored into the policy so the two cannot drift: a tool that
    is not in the registry has no permission class, and `PermissionPolicy` denies
    it as `UNKNOWN_TOOL` regardless of mode.
    """

    def __init__(self, policy: PermissionPolicy) -> None:
        self._policy = policy
        self._definitions: dict[str, ToolDefinition] = {}

    def __len__(self) -> int:
        return len(self._definitions)

    def __contains__(self, tool_name: object) -> bool:
        return tool_name in self._definitions

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    @property
    def policy(self) -> PermissionPolicy:
        return self._policy

    def register(self, definition: ToolDefinition) -> None:
        """Add a tool. Rejected if the name is taken or the class is malformed."""
        if definition.name in self._definitions:
            msg = f"tool {definition.name!r} is already registered"
            raise ValueError(msg)
        if definition.permission_class is PermissionClass.READ_ONLY and definition.parameters:
            unknown_required = set(definition.required_arguments) - set(
                definition.parameters.get("properties", {})
            )
            if unknown_required:
                msg = (
                    f"{definition.name!r} requires undeclared properties: "
                    f"{sorted(unknown_required)}"
                )
                raise ValueError(msg)
        self._definitions[definition.name] = definition
        self._policy.register(definition.name, definition.permission_class)

    def get(self, tool_name: str) -> ToolDefinition | None:
        return self._definitions.get(tool_name)

    def manifest(self) -> list[dict[str, Any]]:
        """Everything the model is allowed to know about, from allowlisted tools only."""
        return [self._definitions[name].manifest_entry() for name in self.names]


class ToolExecutor:
    """The single choke point through which a tool handler can run.

    Nothing else in the codebase calls a handler directly. Every invocation is
    authorized by `PermissionPolicy.decide()` first, which is what makes the
    policy enforceable rather than advisory.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def invoke(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        approval: ApprovalGrant | None = None,
    ) -> ToolResult:
        """Authorize then run a tool call.

        On any denial the handler is never invoked. Handler exceptions are
        captured into the result rather than propagated, so one failing tool
        cannot take down an investigation mid-flight.
        """
        payload: Mapping[str, Any] = arguments or {}
        definition = self._registry.get(tool_name)

        if definition is None:
            decision = self._registry.policy.decide(tool_name, approval=approval)
            return ToolResult(tool_name=tool_name, ok=False, decision=decision)

        decision = self._registry.policy.decide(tool_name, approval=approval)
        if not decision.allowed:
            return ToolResult(tool_name=tool_name, ok=False, decision=decision)

        problem = definition.validate(payload)
        if problem is not None:
            return ToolResult(
                tool_name=tool_name,
                ok=False,
                decision=decision,
                error=problem,
            )

        try:
            value = await definition.handler(payload)
        except Exception as exc:
            return ToolResult(
                tool_name=tool_name,
                ok=False,
                decision=decision,
                error=f"{type(exc).__name__}: {exc}",
            )

        return ToolResult(tool_name=tool_name, ok=True, decision=decision, value=value)


__all__ = [
    "DenialReason",
    "ToolDefinition",
    "ToolExecutor",
    "ToolHandler",
    "ToolRegistry",
    "ToolResult",
]
