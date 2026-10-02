"""Tests for the typed tool registry and the permission-gated executor.

The central claim under test: a tool handler cannot run unless the policy allowed
it. Every denial test therefore asserts both that the result is refused *and*
that the handler recorded no invocation.
"""

from collections.abc import Mapping
from typing import Any

import pytest

from nexus.tools.base import ToolDefinition, ToolExecutor, ToolRegistry
from nexus.tools.permissions import (
    ApprovalGrant,
    DenialReason,
    ExecutionMode,
    PermissionClass,
    PermissionPolicy,
)

PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {"container": {"type": "string"}, "grace_seconds": {"type": "integer"}},
    "required": ["container"],
}


class Recorder:
    """Stands in for a real handler and remembers whether it ran."""

    def __init__(self, value: Any = "ok", raises: Exception | None = None) -> None:
        self.calls: list[Mapping[str, Any]] = []
        self._value = value
        self._raises = raises

    async def __call__(self, arguments: Mapping[str, Any]) -> Any:
        self.calls.append(arguments)
        if self._raises is not None:
            raise self._raises
        return self._value

    @property
    def ran(self) -> bool:
        return bool(self.calls)


def _registry(mode: ExecutionMode = ExecutionMode.READ_ONLY) -> ToolRegistry:
    return ToolRegistry(PermissionPolicy(mode))


def _executor(registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(registry)


def _add(
    registry: ToolRegistry,
    name: str,
    permission_class: PermissionClass,
    handler: Recorder,
    parameters: dict[str, Any] | None = None,
) -> ToolDefinition:
    definition = ToolDefinition(
        name=name,
        description=f"test tool {name}",
        permission_class=permission_class,
        handler=handler,
        parameters=PARAMS if parameters is None else parameters,
    )
    registry.register(definition)
    return definition


def _grant(tool_name: str) -> ApprovalGrant:
    return ApprovalGrant(approval_id="ap-1", tool_name=tool_name, granted_by="human")


class TestRegistryIsAnAllowlist:
    def test_empty_registry_advertises_nothing(self) -> None:
        assert _registry().manifest() == []

    def test_manifest_contains_only_registered_tools(self) -> None:
        registry = _registry()
        _add(registry, "host.disk_usage", PermissionClass.READ_ONLY, Recorder())
        assert [entry["name"] for entry in registry.manifest()] == ["host.disk_usage"]

    def test_registration_populates_names_and_membership(self) -> None:
        registry = _registry()
        _add(registry, "host.disk_usage", PermissionClass.READ_ONLY, Recorder())
        assert registry.names == ("host.disk_usage",)
        assert "host.disk_usage" in registry
        assert "host.shutdown" not in registry
        assert len(registry) == 1

    def test_duplicate_registration_is_refused(self) -> None:
        registry = _registry()
        _add(registry, "host.disk_usage", PermissionClass.READ_ONLY, Recorder())
        with pytest.raises(ValueError, match="already registered"):
            _add(registry, "host.disk_usage", PermissionClass.LOW_RISK, Recorder())

    def test_get_returns_none_for_unknown_tool(self) -> None:
        assert _registry().get("host.shutdown") is None

    def test_registration_mirrors_the_permission_class_into_the_policy(self) -> None:
        registry = _registry()
        _add(registry, "docker.prune_cache", PermissionClass.REQUIRES_APPROVAL, Recorder())
        assert (
            registry.policy.permission_class_for("docker.prune_cache")
            is PermissionClass.REQUIRES_APPROVAL
        )

    def test_registration_rejects_required_args_absent_from_properties(self) -> None:
        registry = _registry()
        malformed = {
            "type": "object",
            "properties": {"container": {"type": "string"}},
            "required": ["container", "host"],
        }
        with pytest.raises(ValueError, match="undeclared properties"):
            _add(registry, "broken.tool", PermissionClass.READ_ONLY, Recorder(), malformed)


class TestManifestDisclosure:
    def test_manifest_states_the_permission_class(self) -> None:
        registry = _registry()
        _add(registry, "docker.prune_cache", PermissionClass.REQUIRES_APPROVAL, Recorder())
        assert registry.manifest()[0]["permission_class"] == "REQUIRES_APPROVAL"

    def test_gated_tools_are_visible_rather_than_hidden(self) -> None:
        """The model is told a gated tool exists, rather than discovering it by rejection."""
        registry = _registry()
        _add(registry, "docker.restart_container", PermissionClass.LOW_RISK, Recorder())
        _add(registry, "host.disk_usage", PermissionClass.READ_ONLY, Recorder())
        assert {entry["name"] for entry in registry.manifest()} == {
            "docker.restart_container",
            "host.disk_usage",
        }


class TestArgumentValidation:
    def _definition(self, **overrides: Any) -> ToolDefinition:
        defaults: dict[str, Any] = {
            "name": "docker.restart_container",
            "description": "d",
            "permission_class": PermissionClass.READ_ONLY,
            "handler": Recorder(),
            "parameters": PARAMS,
        }
        return ToolDefinition(**{**defaults, **overrides})

    def test_missing_required_argument_is_reported(self) -> None:
        assert self._definition().validate({}) == "missing required argument(s): container"

    def test_unknown_argument_is_reported(self) -> None:
        problem = self._definition().validate({"container": "immich", "sudo": "rm -rf /"})
        assert problem is not None
        assert "unknown argument(s): sudo" in problem

    def test_valid_arguments_pass(self) -> None:
        assert self._definition().validate({"container": "immich"}) is None

    def test_schema_without_properties_accepts_anything(self) -> None:
        assert self._definition(parameters={}).validate({"anything": 1}) is None

    async def test_invalid_arguments_stop_the_handler(self) -> None:
        recorder = Recorder()
        registry = _registry()
        _add(registry, "host.disk_usage", PermissionClass.READ_ONLY, recorder)
        result = await _executor(registry).invoke("host.disk_usage", {})
        assert result.ok is False
        assert result.error == "missing required argument(s): container"
        assert recorder.ran is False


class TestExecutorEnforcesPolicy:
    async def test_read_only_tool_runs_in_default_mode(self) -> None:
        recorder = Recorder(value={"used_pct": 91})
        registry = _registry()
        _add(registry, "host.disk_usage", PermissionClass.READ_ONLY, recorder)
        result = await _executor(registry).invoke("host.disk_usage", {"container": "immich"})
        assert result.ok is True
        assert result.value == {"used_pct": 91}
        assert result.denied is False
        assert recorder.calls == [{"container": "immich"}]

    async def test_low_risk_tool_is_refused_in_read_only_mode_and_never_runs(self) -> None:
        recorder = Recorder()
        registry = _registry()
        _add(registry, "docker.restart_container", PermissionClass.LOW_RISK, recorder)
        result = await _executor(registry).invoke(
            "docker.restart_container", {"container": "immich"}
        )
        assert result.ok is False
        assert result.denied is True
        assert result.decision.denial is DenialReason.READ_ONLY_MODE
        assert recorder.ran is False

    async def test_low_risk_tool_runs_once_mode_is_permissive(self) -> None:
        recorder = Recorder()
        registry = _registry(ExecutionMode.PERMISSIVE)
        _add(registry, "docker.restart_container", PermissionClass.LOW_RISK, recorder)
        result = await _executor(registry).invoke(
            "docker.restart_container", {"container": "immich"}
        )
        assert result.ok is True
        assert recorder.ran is True

    async def test_forbidden_tool_never_runs_even_in_permissive_mode(self) -> None:
        recorder = Recorder()
        registry = _registry(ExecutionMode.PERMISSIVE)
        _add(registry, "host.exec_shell", PermissionClass.FORBIDDEN, recorder)
        result = await _executor(registry).invoke("host.exec_shell", {"container": "immich"})
        assert result.ok is False
        assert result.decision.denial is DenialReason.FORBIDDEN_TOOL
        assert recorder.ran is False

    async def test_unregistered_tool_is_refused_as_unknown(self) -> None:
        registry = _registry(ExecutionMode.PERMISSIVE)
        result = await _executor(registry).invoke("host.shutdown", {})
        assert result.ok is False
        assert result.decision.denial is DenialReason.UNKNOWN_TOOL

    async def test_approval_gated_tool_reports_needs_approval(self) -> None:
        recorder = Recorder()
        registry = _registry(ExecutionMode.PERMISSIVE)
        _add(registry, "docker.prune_cache", PermissionClass.REQUIRES_APPROVAL, recorder)
        result = await _executor(registry).invoke("docker.prune_cache", {"container": "immich"})
        assert result.ok is False
        assert result.needs_approval is True
        assert recorder.ran is False

    async def test_approval_gated_tool_runs_with_a_valid_grant(self) -> None:
        recorder = Recorder()
        registry = _registry(ExecutionMode.PERMISSIVE)
        _add(registry, "docker.prune_cache", PermissionClass.REQUIRES_APPROVAL, recorder)
        result = await _executor(registry).invoke(
            "docker.prune_cache", {"container": "immich"}, approval=_grant("docker.prune_cache")
        )
        assert result.ok is True
        assert recorder.ran is True

    async def test_grant_for_another_tool_does_not_unlock(self) -> None:
        recorder = Recorder()
        registry = _registry(ExecutionMode.PERMISSIVE)
        _add(registry, "docker.prune_cache", PermissionClass.REQUIRES_APPROVAL, recorder)
        result = await _executor(registry).invoke(
            "docker.prune_cache",
            {"container": "immich"},
            approval=_grant("docker.restart_container"),
        )
        assert result.ok is False
        assert recorder.ran is False


class TestFailureContainment:
    async def test_handler_exception_is_captured_not_propagated(self) -> None:
        recorder = Recorder(raises=RuntimeError("docker socket missing"))
        registry = _registry()
        _add(registry, "host.disk_usage", PermissionClass.READ_ONLY, recorder)
        result = await _executor(registry).invoke("host.disk_usage", {"container": "immich"})
        assert result.ok is False
        assert result.error == "RuntimeError: docker socket missing"

    async def test_captured_failure_still_reports_the_permitting_decision(self) -> None:
        """A tool that failed is not the same as a tool that was refused."""
        registry = _registry()
        _add(registry, "host.disk_usage", PermissionClass.READ_ONLY, Recorder(raises=OSError("x")))
        result = await _executor(registry).invoke("host.disk_usage", {"container": "immich"})
        assert result.denied is False
        assert result.needs_approval is False

    async def test_handler_returning_none_is_success_not_failure(self) -> None:
        registry = _registry()
        _add(registry, "host.disk_usage", PermissionClass.READ_ONLY, Recorder(value=None))
        result = await _executor(registry).invoke("host.disk_usage", {"container": "immich"})
        assert result.ok is True
        assert result.value is None

    async def test_arguments_default_to_empty_mapping(self) -> None:
        recorder = Recorder()
        registry = _registry()
        _add(registry, "host.disk_usage", PermissionClass.READ_ONLY, recorder, parameters={})
        result = await _executor(registry).invoke("host.disk_usage")
        assert result.ok is True
        assert recorder.calls == [{}]
