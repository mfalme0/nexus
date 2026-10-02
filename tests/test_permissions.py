"""Tests for the tool permission policy.

These tests encode the safety guarantees as executable statements. If a change
makes one of them fail, the change has removed a guarantee, not merely altered
behaviour.
"""

from datetime import UTC, datetime, timedelta

import pytest

from nexus.tools.permissions import (
    ApprovalGrant,
    DenialReason,
    ExecutionMode,
    PermissionClass,
    PermissionPolicy,
)

PERMISSIVE = ExecutionMode.PERMISSIVE
READ_ONLY = ExecutionMode.READ_ONLY


def _policy(mode: ExecutionMode = READ_ONLY) -> PermissionPolicy:
    policy = PermissionPolicy(mode)
    policy.register("host.disk_usage", PermissionClass.READ_ONLY)
    policy.register("docker.restart_container", PermissionClass.LOW_RISK)
    policy.register("docker.prune_cache", PermissionClass.REQUIRES_APPROVAL)
    policy.register("host.exec_shell", PermissionClass.FORBIDDEN)
    return policy


def _grant(tool_name: str, **kwargs: object) -> ApprovalGrant:
    defaults: dict[str, object] = {
        "approval_id": "ap-1",
        "tool_name": tool_name,
        "granted_by": "human",
    }
    return ApprovalGrant(**{**defaults, **kwargs})  # type: ignore[arg-type]


class TestAllowlistDefault:
    """An unregistered tool must never run. This is the allowlist guarantee."""

    def test_fresh_policy_denies_everything(self) -> None:
        policy = PermissionPolicy()
        assert policy.registered_tools == frozenset()
        decision = policy.decide("anything.at.all")
        assert decision.allowed is False
        assert decision.denial is DenialReason.UNKNOWN_TOOL

    def test_tool_omitted_from_registry_is_denied(self) -> None:
        policy = _policy()
        decision = policy.decide("host.shutdown")
        assert decision.allowed is False
        assert decision.denial is DenialReason.UNKNOWN_TOOL
        assert decision.permission_class is None

    def test_unregistered_tool_denied_even_in_permissive_mode_with_approval(self) -> None:
        """Registration is the gate. Mode and approval cannot substitute for it."""
        policy = _policy(PERMISSIVE)
        decision = policy.decide("host.shutdown", approval=_grant("host.shutdown"))
        assert decision.allowed is False
        assert decision.denial is DenialReason.UNKNOWN_TOOL


class TestForbidden:
    """FORBIDDEN must be unreachable by every combination of mode and approval."""

    def test_forbidden_denied_in_read_only_mode(self) -> None:
        assert _policy().decide("host.exec_shell").denial is DenialReason.FORBIDDEN_TOOL

    def test_forbidden_denied_in_permissive_mode(self) -> None:
        assert _policy(PERMISSIVE).decide("host.exec_shell").denial is DenialReason.FORBIDDEN_TOOL

    def test_forbidden_denied_despite_valid_approval(self) -> None:
        decision = _policy(PERMISSIVE).decide("host.exec_shell", approval=_grant("host.exec_shell"))
        assert decision.allowed is False
        assert decision.denial is DenialReason.FORBIDDEN_TOOL

    def test_forbidden_takes_precedence_over_unknown_tool_check(self) -> None:
        """A registered FORBIDDEN tool reports FORBIDDEN, not UNKNOWN_TOOL."""
        policy = PermissionPolicy(PERMISSIVE)
        policy.register("host.exec_shell", PermissionClass.FORBIDDEN)
        decision = policy.decide("host.exec_shell")
        assert decision.denial is DenialReason.FORBIDDEN_TOOL


class TestExecutionMode:
    def test_read_only_allowed_in_default_mode(self) -> None:
        assert _policy().decide("host.disk_usage").allowed is True

    def test_read_only_allowed_in_permissive_mode(self) -> None:
        assert _policy(PERMISSIVE).decide("host.disk_usage").allowed is True

    def test_low_risk_denied_in_default_read_only_mode(self) -> None:
        decision = _policy().decide("docker.restart_container")
        assert decision.allowed is False
        assert decision.denial is DenialReason.READ_ONLY_MODE

    def test_low_risk_allowed_in_permissive_mode_without_approval(self) -> None:
        """LOW_RISK needs a permissive mode but not a human grant."""
        assert _policy(PERMISSIVE).decide("docker.restart_container").allowed is True

    def test_low_risk_still_denied_in_read_only_mode_even_with_approval(self) -> None:
        decision = _policy().decide(
            "docker.restart_container", approval=_grant("docker.restart_container")
        )
        assert decision.allowed is False
        assert decision.denial is DenialReason.READ_ONLY_MODE


class TestApprovalRequired:
    def test_requires_approval_denied_without_grant_in_permissive_mode(self) -> None:
        decision = _policy(PERMISSIVE).decide("docker.prune_cache")
        assert decision.allowed is False
        assert decision.denial is DenialReason.APPROVAL_REQUIRED
        assert decision.needs_approval is True

    def test_allows_permissive_mode_with_valid_grant(self) -> None:
        decision = _policy(PERMISSIVE).decide(
            "docker.prune_cache", approval=_grant("docker.prune_cache")
        )
        assert decision.allowed is True
        assert decision.needs_approval is False

    def test_still_denied_in_read_only_mode_with_valid_grant(self) -> None:
        """Approval does not itself escalate the execution mode."""
        decision = _policy().decide("docker.prune_cache", approval=_grant("docker.prune_cache"))
        assert decision.allowed is False
        assert decision.denial is DenialReason.READ_ONLY_MODE

    def test_grant_for_a_different_tool_is_rejected(self) -> None:
        """A grant is bound to one tool and cannot be replayed sideways."""
        decision = _policy(PERMISSIVE).decide(
            "docker.prune_cache", approval=_grant("docker.restart_container")
        )
        assert decision.allowed is False
        assert decision.denial is DenialReason.APPROVAL_REQUIRED

    def test_consumed_grant_is_rejected(self) -> None:
        used = _grant("docker.prune_cache", consumed=True)
        assert _policy(PERMISSIVE).decide("docker.prune_cache", approval=used).allowed is False

    def test_expired_grant_is_rejected(self) -> None:
        grant = _grant("docker.prune_cache", expires_at=datetime.now(UTC) - timedelta(minutes=1))
        assert grant.is_expired() is True
        decision = _policy(PERMISSIVE).decide("docker.prune_cache", approval=grant)
        assert decision.allowed is False
        assert decision.denial is DenialReason.APPROVAL_REQUIRED

    def test_grant_expiry_honours_an_injected_clock(self) -> None:
        now = datetime.now(UTC)
        grant = _grant("docker.prune_cache", expires_at=now + timedelta(minutes=5))
        assert grant.is_expired(now) is False
        assert grant.is_expired(now + timedelta(minutes=6)) is True

    def test_grant_without_expiry_never_expires(self) -> None:
        assert _grant("docker.prune_cache").is_expired() is False

    def test_grant_inside_its_window_is_accepted(self) -> None:
        grant = _grant("docker.prune_cache", expires_at=datetime.now(UTC) + timedelta(minutes=5))
        assert _policy(PERMISSIVE).decide("docker.prune_cache", approval=grant).allowed is True


class TestRegistrationInvariants:
    def test_permission_class_cannot_be_silently_changed(self) -> None:
        policy = _policy()
        with pytest.raises(ValueError, match="already registered"):
            policy.register("docker.prune_cache", PermissionClass.READ_ONLY)

    def test_rejected_re_registration_leaves_original_class_intact(self) -> None:
        policy = _policy()
        with pytest.raises(ValueError, match="already registered"):
            policy.register("docker.prune_cache", PermissionClass.READ_ONLY)
        assert (
            policy.permission_class_for("docker.prune_cache") is PermissionClass.REQUIRES_APPROVAL
        )

    def test_permission_class_lookup_returns_none_for_unknown(self) -> None:
        assert _policy().permission_class_for("nope") is None


class TestDecisionShape:
    def test_allowed_decision_reports_no_denial(self) -> None:
        decision = _policy().decide("host.disk_usage")
        assert decision.denial is None
        assert isinstance(decision.reason, str)

    def test_denied_decision_reports_a_denial_reason(self) -> None:
        decision = _policy().decide("docker.restart_container")
        assert isinstance(decision.denial, DenialReason)

    def test_needs_approval_is_false_for_plain_denial(self) -> None:
        assert _policy().decide("host.shutdown").needs_approval is False
