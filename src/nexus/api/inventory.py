"""Read-only inventory endpoints.

This module exposes the Phase 2 discovery layer over HTTP. It is the first place
where the permission policy is visible from outside the process, so it is also the
first place someone might be tempted to route around it. Three rules hold here:

- The registry is a dependency, not a module global, so a test can substitute a
  sandboxed probe set without the endpoint growing a bypass parameter.
- Every invocation goes through `ToolExecutor`. There is no path in this module
  that calls a handler directly.
- **An unknown tool name is an authorization outcome, not a routing one.** It is
  reported as `403` with a `DenialReason`, not `404`. Returning 404 would tell an
  unauthenticated caller which names are not merely absent but deliberately
  unlisted, turning the allowlist into an enumeration oracle.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from nexus.config import settings
from nexus.security.approvals import ApprovalStore
from nexus.services.discovery import build_read_only_registry, collect_inventory
from nexus.tools.base import ToolExecutor, ToolRegistry, ToolResult

router = APIRouter()


def get_registry() -> ToolRegistry:
    """Build the read-only tool registry from settings.

    Overridable via FastAPI dependency overrides, which is how the tests point the
    probes at fixtures.
    """
    return build_read_only_registry(
        root_path=settings.host_tools.disk_path,
        meminfo_path=settings.host_tools.meminfo_path,
    )


def get_executor(
    registry: Annotated[ToolRegistry, Depends(get_registry)],
) -> ToolExecutor:
    return ToolExecutor(registry)


def get_approval_store() -> ApprovalStore:
    """The approval store.

    A fresh, empty store per request is correct here: nothing in the HTTP layer can
    issue approvals, so there is nothing to persist. It arrives as a dependency so
    the Phase 8 approval flow can replace it with the real thing.
    """
    return ApprovalStore()


class EvidenceResponse(BaseModel):
    """One observation, with its provenance and an explicit status."""

    status: str
    source: str
    observed_at: str
    value: dict[str, Any] | None = None
    detail: str | None = None
    claim: str


class InventoryResponse(BaseModel):
    """A host snapshot. Gaps are represented, never omitted."""

    hostname: str | None
    observed_at: str
    complete: bool
    coverage_ratio: float
    gaps: list[str]
    evidence: dict[str, EvidenceResponse]


class ToolResponse(BaseModel):
    """One allowlisted tool, as advertised to the model and to operators."""

    name: str
    description: str
    parameters: dict[str, Any]
    permission_class: str


class InvocationRequest(BaseModel):
    """Body for a tool invocation.

    `approval_id` may *reference* a grant issued by the approval flow but can never
    create one. An unrecognised id resolves to no approval, so a caller cannot
    approve its own action by inventing an identifier.
    """

    arguments: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = None


@router.get("/inventory/host", response_model=InventoryResponse, tags=["inventory"])
async def host_inventory(
    executor: Annotated[ToolExecutor, Depends(get_executor)],
) -> InventoryResponse:
    """Run the read-only host probes and return the resulting snapshot.

    Always returns 200. A host that cannot be fully observed is a normal, expected
    outcome that the body describes, not an error.
    """
    inventory = await collect_inventory(executor.registry)
    return InventoryResponse(**inventory.to_dict())


@router.get("/tools", response_model=list[ToolResponse], tags=["tools"])
async def list_tools(
    executor: Annotated[ToolExecutor, Depends(get_executor)],
) -> list[ToolResponse]:
    """List the allowlisted tools and their permission classes."""
    return [ToolResponse(**entry) for entry in executor.registry.manifest()]


@router.post("/tools/{tool_name}", tags=["tools"])
async def invoke_tool(
    tool_name: str,
    payload: InvocationRequest,
    executor: Annotated[ToolExecutor, Depends(get_executor)],
    approvals: Annotated[ApprovalStore, Depends(get_approval_store)],
) -> dict[str, Any]:
    """Invoke a tool, subject to the permission policy.

    Status codes distinguish the three outcomes that matter:

    - `200` the tool ran (or ran and failed; the body says which)
    - `400` arguments were unusable
    - `403` the policy refused, including unknown and FORBIDDEN tool names
    """
    approval = approvals.resolve(payload.approval_id) if payload.approval_id else None
    result = await executor.invoke(tool_name, payload.arguments, approval=approval)

    if result.decision.needs_approval:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "tool": tool_name,
                "denial": str(result.decision.reason),
                "needs_approval": True,
                "message": "This tool requires an explicit human approval before it can run.",
            },
        )

    if result.denied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "tool": tool_name,
                "denial": str(result.decision.reason),
                "needs_approval": False,
                "message": str(result.decision.reason),
            },
        )

    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"tool": tool_name, "error": result.error or "tool failed"},
        )

    return {"tool": tool_name, "ok": True, "value": _serializable(result)}


def _serializable(result: ToolResult) -> Any:
    """Convert a tool's return value into something JSON-encodable."""
    value = result.value
    as_claim = getattr(value, "as_claim", None)
    if callable(as_claim):
        return {
            "status": str(value.status),
            "source": value.source,
            "value": value.value,
            "detail": value.detail,
            "claim": as_claim(),
        }
    return value


__all__ = [
    "EvidenceResponse",
    "InventoryResponse",
    "InvocationRequest",
    "ToolResponse",
    "get_executor",
    "get_registry",
    "router",
]
