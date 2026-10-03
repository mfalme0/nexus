"""Tests for the inventory and tool HTTP endpoints.

The probes are pointed at a temporary directory via a dependency override, so
these tests never read the real machine's `/proc` or root filesystem and assert
the same thing on any platform.
"""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pytest_asyncio import fixture

from nexus.api.inventory import get_approval_store, get_registry
from nexus.main import create_app
from nexus.security.approvals import ApprovalStore
from nexus.services.discovery import build_read_only_registry
from nexus.tools.base import ToolDefinition, ToolRegistry
from nexus.tools.host import register_host_tools
from nexus.tools.permissions import ExecutionMode, PermissionClass, PermissionPolicy

MEMINFO = "MemTotal: 1024 kB\nMemAvailable: 256 kB\n"


def _sandbox_registry(tmp_path: Path) -> ToolRegistry:
    """A read-only registry pointed at a temp directory with a synthetic meminfo."""
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(MEMINFO, encoding="utf-8")
    return build_read_only_registry(
        root_path=str(tmp_path),
        meminfo_path=str(meminfo),
    )


def _app_for(
    registry: ToolRegistry,
    approvals: ApprovalStore | None = None,
) -> FastAPI:
    """An app whose tool registry and approval store are both overridden."""
    app = create_app()
    app.dependency_overrides[get_registry] = lambda: registry
    if approvals is not None:
        app.dependency_overrides[get_approval_store] = lambda: approvals
    return app


@asynccontextmanager
async def _client_for(
    registry: ToolRegistry,
    approvals: ApprovalStore | None = None,
) -> AsyncGenerator[AsyncClient, None]:
    """Drive the API against an overridden registry, then restore the app."""
    app = _app_for(registry, approvals)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@fixture
def sandbox_registry(tmp_path: Path) -> ToolRegistry:
    return _sandbox_registry(tmp_path)


@fixture
async def sandbox_client(sandbox_registry: ToolRegistry) -> AsyncGenerator[AsyncClient, None]:
    async with _client_for(sandbox_registry) as client:
        yield client


class TestInventoryEndpoint:
    async def test_returns_200(self, sandbox_client) -> None:
        assert (await sandbox_client.get("/api/v1/inventory/host")).status_code == 200

    async def test_body_carries_the_inventory_shape(self, sandbox_client) -> None:
        body = (await sandbox_client.get("/api/v1/inventory/host")).json()
        assert set(body) >= {
            "hostname",
            "observed_at",
            "complete",
            "coverage_ratio",
            "gaps",
            "evidence",
        }

    async def test_evidence_entries_include_a_claim_and_status(self, sandbox_client) -> None:
        body = (await sandbox_client.get("/api/v1/inventory/host")).json()
        memory = body["evidence"]["memory"]
        assert memory["status"] in ("OBSERVED", "UNAVAILABLE")
        assert memory["claim"]
        assert memory["source"]

    async def test_gaps_are_listed_rather_than_omitted(self, sandbox_client) -> None:
        """A partially observed host still returns 200 and names what it missed."""
        body = (await sandbox_client.get("/api/v1/inventory/host")).json()
        assert isinstance(body["gaps"], list)
        assert set(body["gaps"]) <= set(body["evidence"])

    async def test_unobserved_host_is_not_an_http_error(self, tmp_path: Path) -> None:
        """No meminfo file at all: still 200, with the gap named."""
        registry = build_read_only_registry(
            root_path=str(tmp_path), meminfo_path=str(tmp_path / "absent")
        )
        async with _client_for(registry) as client:
            response = await client.get("/api/v1/inventory/host")
            body = response.json()
        assert response.status_code == 200
        assert "memory" in body["gaps"]
        assert body["evidence"]["memory"]["status"] == "UNAVAILABLE"


class TestToolListing:
    async def test_lists_allowlisted_tools(self, sandbox_client) -> None:
        body = (await sandbox_client.get("/api/v1/tools")).json()
        assert {entry["name"] for entry in body} >= {"host.disk_usage", "host.memory"}

    async def test_each_entry_declares_its_permission_class(self, sandbox_client) -> None:
        body = (await sandbox_client.get("/api/v1/tools")).json()
        assert all(entry["permission_class"] == "READ_ONLY" for entry in body)


class TestToolInvocation:
    async def test_read_only_tool_invocation_succeeds(self, sandbox_client) -> None:
        response = await sandbox_client.post("/api/v1/tools/host.memory", json={"arguments": {}})
        assert response.status_code == 200
        assert response.json()["ok"] is True

    async def test_successful_invocation_returns_a_claim(self, sandbox_client) -> None:
        body = (
            await sandbox_client.post("/api/v1/tools/host.memory", json={"arguments": {}})
        ).json()
        assert body["value"]["claim"]

    async def test_unknown_tool_is_forbidden_not_not_found(self, sandbox_client) -> None:
        """404 would turn the allowlist into an enumeration oracle."""
        response = await sandbox_client.post("/api/v1/tools/host.shutdown", json={})
        assert response.status_code == 403
        assert response.json()["detail"]["denial"] == "UNKNOWN_TOOL"

    async def test_empty_registry_refuses_every_invocation(self) -> None:
        async with _client_for(ToolRegistry(PermissionPolicy())) as client:
            response = await client.post("/api/v1/tools/host.memory", json={})
        assert response.status_code == 403
        assert response.json()["detail"]["denial"] == "UNKNOWN_TOOL"


def _gated_registry(mode: ExecutionMode) -> ToolRegistry:
    """A permissive registry that also carries a destructive, approval-gated tool."""

    async def handler(_arguments: Mapping[str, Any]) -> dict[str, bool]:
        return {"pruned": True}

    registry = ToolRegistry(PermissionPolicy(mode))
    register_host_tools(registry, root_path="/", meminfo_path="/proc/meminfo")
    registry.register(
        ToolDefinition(
            name="docker.prune_cache",
            description="destructive",
            permission_class=PermissionClass.REQUIRES_APPROVAL,
            handler=handler,
        )
    )
    return registry


class TestApprovalGateOverHttp:
    async def test_gated_tool_is_refused_without_approval(self) -> None:
        async with _client_for(_gated_registry(ExecutionMode.PERMISSIVE)) as client:
            response = await client.post("/api/v1/tools/docker.prune_cache", json={})
        assert response.status_code == 403
        assert response.json()["detail"]["needs_approval"] is True

    async def test_caller_cannot_mint_its_own_approval(self) -> None:
        """A self-issued approval_id must not unlock anything.

        This is the regression test for a real hole in the first draft of this
        endpoint: it built an ApprovalGrant straight from the request body, so any
        caller could approve its own action by inventing an identifier.
        """
        async with _client_for(_gated_registry(ExecutionMode.PERMISSIVE)) as client:
            response = await client.post(
                "/api/v1/tools/docker.prune_cache",
                json={"arguments": {}, "approval_id": "self-issued"},
            )
        assert response.status_code == 403
        assert response.json()["detail"]["needs_approval"] is True

    async def test_gated_tool_runs_with_a_genuinely_issued_approval(self) -> None:
        store = ApprovalStore()
        grant = store.issue("docker.prune_cache", granted_by="operator")
        async with _client_for(
            _gated_registry(ExecutionMode.PERMISSIVE), approvals=store
        ) as client:
            response = await client.post(
                "/api/v1/tools/docker.prune_cache",
                json={"arguments": {}, "approval_id": grant.approval_id},
            )
        assert response.status_code == 200
        assert response.json()["value"] == {"pruned": True}

    async def test_approval_for_another_tool_does_not_unlock(self) -> None:
        store = ApprovalStore()
        grant = store.issue("host.memory", granted_by="operator")
        async with _client_for(
            _gated_registry(ExecutionMode.PERMISSIVE), approvals=store
        ) as client:
            response = await client.post(
                "/api/v1/tools/docker.prune_cache",
                json={"arguments": {}, "approval_id": grant.approval_id},
            )
        assert response.status_code == 403
        assert response.json()["detail"]["needs_approval"] is True

    async def test_gated_tool_stays_refused_in_read_only_mode(self) -> None:
        store = ApprovalStore()
        grant = store.issue("docker.prune_cache", granted_by="operator")
        async with _client_for(_gated_registry(ExecutionMode.READ_ONLY), approvals=store) as client:
            response = await client.post(
                "/api/v1/tools/docker.prune_cache",
                json={"arguments": {}, "approval_id": grant.approval_id},
            )
        assert response.status_code == 403
        assert response.json()["detail"]["denial"] == "READ_ONLY_MODE"


class TestForbiddenToolOverHttp:
    async def test_forbidden_tool_is_rejected_even_in_permissive_mode(self) -> None:
        registry = _gated_registry(ExecutionMode.PERMISSIVE)

        async def handler(_arguments: Mapping[str, Any]) -> None:
            return None

        registry.register(
            ToolDefinition(
                name="host.exec_shell",
                description="arbitrary shell",
                permission_class=PermissionClass.FORBIDDEN,
                handler=handler,
            )
        )
        async with _client_for(registry) as client:
            response = await client.post("/api/v1/tools/host.exec_shell", json={})
        assert response.status_code == 403
        assert response.json()["detail"]["denial"] == "FORBIDDEN_TOOL"


class TestRouting:
    async def test_health_endpoint_unaffected(self, sandbox_client) -> None:
        assert (await sandbox_client.get("/api/v1/health")).status_code == 200

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/api/v1/inventory/host"),
            ("get", "/api/v1/tools"),
            ("post", "/api/v1/tools/{tool_name}"),
            ("get", "/api/v1/health"),
        ],
    )
    def test_routes_are_published_in_the_openapi_schema(
        self,
        method: str,
        path: str,
        sandbox_registry: ToolRegistry,
    ) -> None:
        app = create_app()
        app.dependency_overrides[get_registry] = lambda: sandbox_registry
        try:
            paths = app.openapi()["paths"]
        finally:
            app.dependency_overrides.clear()
        assert path in paths
        assert method in paths[path]
