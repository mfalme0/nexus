"""Tests for the read-only host probes and local discovery.

Probes are tested against real sources where possible: a real temporary directory
for disk usage, and a synthetic `/proc/meminfo` for parsing. The unavailable paths
are tested by pointing at a path that genuinely does not exist, so those tests
assert real behaviour rather than a mocked stand-in.
"""

import os
from pathlib import Path
from typing import Any

import pytest

from nexus.services.discovery import (
    INVENTORY_KEYS,
    build_read_only_registry,
    collect_inventory,
    tool_name_for,
)
from nexus.tools.base import ToolExecutor, ToolRegistry
from nexus.tools.evidence import Evidence, EvidenceStatus
from nexus.tools.host import _parse_meminfo, host_tool_definitions, register_host_tools
from nexus.tools.permissions import PermissionClass, PermissionPolicy

pytestmark = pytest.mark.unit

MEMINFO = """MemTotal:       16384000 kB
MemFree:         2048000 kB
MemAvailable:   12288000 kB
Buffers:          262144 kB
SwapTotal:       2097152 kB
SwapFree:        2097152 kB
"""

# `host.load` genuinely cannot observe anything where `os.getloadavg` is absent, so
# on such a platform it is a real, expected gap rather than a failure. Expectations
# below are derived from this instead of hard-coded, so the suite asserts the same
# thing on a developer laptop and on the Linux CI runner.
PLATFORM_GAPS: tuple[str, ...] = () if getattr(os, "getloadavg", None) is not None else ("load",)


def _registry(tmp_path: Path, *, with_memory: bool = True) -> ToolRegistry:
    meminfo = tmp_path / "meminfo"
    if with_memory:
        meminfo.write_text(MEMINFO, encoding="utf-8")
    return build_read_only_registry(
        root_path=str(tmp_path),
        meminfo_path=str(meminfo),
    )


class TestEvidenceRecord:
    def test_observed_evidence_is_marked_observed(self) -> None:
        evidence = Evidence.observed_value("disk_usage", "statvfs", {"used_pct": 91.0})
        assert evidence.observed is True
        assert evidence.required_evidence_covered is True

    def test_unavailable_evidence_carries_a_reason_and_no_value(self) -> None:
        evidence = Evidence.unavailable("disk_usage", "statvfs", "host did not respond")
        assert evidence.observed is False
        assert evidence.value is None
        assert evidence.detail == "host did not respond"

    def test_claim_quotes_the_source_when_observed(self) -> None:
        evidence = Evidence.observed_value("disk_usage", "statvfs", {"used_pct": 91.0})
        assert "observed from statvfs" in evidence.as_claim()

    def test_claim_states_an_inability_to_verify_when_not_observed(self) -> None:
        """The gap must read as a gap, not as an absent field."""
        evidence = Evidence.unavailable("disk_usage", "statvfs", "host did not respond")
        claim = evidence.as_claim()
        assert "could not verify" in claim
        assert "host did not respond" in claim

    def test_unavailable_claim_falls_back_when_no_detail_given(self) -> None:
        assert "source unavailable" in Evidence("k", EvidenceStatus.UNAVAILABLE, "s").as_claim()


class TestDiskUsageProbe:
    async def test_reports_usage_for_a_real_path(self, tmp_path: Path) -> None:
        registry = _registry(tmp_path)
        result = await ToolExecutor(registry).invoke("host.disk_usage", {})
        assert result.ok is True
        assert isinstance(result.value, Evidence)
        assert result.value.observed is True
        assert result.value.value is not None
        assert result.value.value["total_bytes"] > 0
        assert 0 <= result.value.value["used_pct"] <= 100

    async def test_missing_path_yields_unavailable_not_an_exception(self, tmp_path: Path) -> None:
        registry = build_read_only_registry(root_path=str(tmp_path / "nope"))
        result = await ToolExecutor(registry).invoke("host.disk_usage", {})
        assert result.ok is True
        assert isinstance(result.value, Evidence)
        assert result.value.observed is False
        assert "disk_usage" in result.value.as_claim()


class TestMeminfoParsing:
    def test_parses_kilobyte_fields_into_bytes(self) -> None:
        evidence = _parse_meminfo(MEMINFO, "test")
        assert evidence.observed is True
        assert evidence.value is not None
        assert evidence.value["total_bytes"] == 16384000 * 1024
        assert evidence.value["available_bytes"] == 12288000 * 1024

    def test_computes_used_as_total_minus_available(self) -> None:
        evidence = _parse_meminfo(MEMINFO, "test")
        assert evidence.value is not None
        assert evidence.value["used_bytes"] == (
            evidence.value["total_bytes"] - evidence.value["available_bytes"]
        )

    def test_used_pct_is_a_percentage(self) -> None:
        evidence = _parse_meminfo(MEMINFO, "test")
        assert evidence.value is not None
        assert 0 < evidence.value["used_pct"] < 100

    def test_empty_input_is_unavailable(self) -> None:
        assert _parse_meminfo("", "test").observed is False

    def test_missing_required_field_is_unavailable(self) -> None:
        evidence = _parse_meminfo("SwapTotal: 100 kB\n", "test")
        assert evidence.observed is False
        assert "MemTotal" in (evidence.detail or "")

    def test_unparsable_lines_are_skipped_not_fatal(self) -> None:
        noisy = "garbage line\nMemTotal: 1024 kB\nMemAvailable: 512 kB\n"
        evidence = _parse_meminfo(noisy, "test")
        assert evidence.observed is True
        assert evidence.value is not None
        assert evidence.value["total_bytes"] == 1024 * 1024

    async def test_absent_meminfo_file_yields_unavailable(self, tmp_path: Path) -> None:
        registry = _registry(tmp_path, with_memory=False)
        result = await ToolExecutor(registry).invoke("host.memory", {})
        assert isinstance(result.value, Evidence)
        assert result.value.observed is False


class TestRegistration:
    def test_registers_every_inventory_probe(self, tmp_path: Path) -> None:
        registry = _registry(tmp_path)
        for key in INVENTORY_KEYS:
            assert tool_name_for(key) in registry

    def test_all_host_tools_are_read_only(self, tmp_path: Path) -> None:
        definitions = host_tool_definitions(root_path=str(tmp_path))
        classes = {definition.permission_class for definition in definitions}
        assert len(classes) == 1
        assert PermissionClass.READ_ONLY in classes

    def test_registration_mirrors_into_the_policy(self, tmp_path: Path) -> None:
        registry = _registry(tmp_path)
        assert registry.policy.permission_class_for("host.disk_usage") is not None

    def test_registering_twice_is_refused(self, tmp_path: Path) -> None:
        registry = _registry(tmp_path)
        with pytest.raises(ValueError, match="already registered"):
            register_host_tools(registry, root_path=str(tmp_path))


class TestInventory:
    async def test_collects_evidence_for_every_probe(self, tmp_path: Path) -> None:
        inventory = await collect_inventory(_registry(tmp_path))
        assert set(inventory.evidence) == set(INVENTORY_KEYS)

    async def test_complete_when_every_probe_succeeds(self, tmp_path: Path) -> None:
        registry = _registry(tmp_path)
        inventory = await collect_inventory(registry)
        assert inventory.gaps == PLATFORM_GAPS
        assert inventory.coverage_ratio == (1.0 if not PLATFORM_GAPS else 4 / 5)
        assert inventory.complete is (not PLATFORM_GAPS)

    async def test_missing_probe_is_recorded_as_a_gap_not_an_absence(self, tmp_path: Path) -> None:
        """A probe that is not registered must not look like a host without it."""
        empty = ToolRegistry(PermissionPolicy())
        inventory = await collect_inventory(empty)
        assert set(inventory.gaps) == set(INVENTORY_KEYS)
        assert inventory.complete is False
        assert inventory.coverage_ratio == 0.0

    async def test_partial_coverage_reports_only_the_failing_key(self, tmp_path: Path) -> None:
        registry = _registry(tmp_path, with_memory=False)
        inventory = await collect_inventory(registry)
        assert inventory.gaps == ("memory", *PLATFORM_GAPS)
        assert 0 < inventory.coverage_ratio < 1
        assert inventory.value("memory") is None

    async def test_value_returns_none_for_unavailable_key(self, tmp_path: Path) -> None:
        inventory = await collect_inventory(_registry(tmp_path, with_memory=False))
        assert inventory.value("memory") is None

    async def test_hostname_is_extracted_from_os_evidence(self, tmp_path: Path) -> None:
        inventory = await collect_inventory(_registry(tmp_path))
        assert inventory.hostname
        assert inventory.value("os") is not None

    async def test_claims_include_gap_sentences(self, tmp_path: Path) -> None:
        inventory = await collect_inventory(_registry(tmp_path, with_memory=False))
        claims = inventory.claims()
        assert any("could not verify" in claim for claim in claims)

    async def test_to_dict_keeps_gaps_visible(self, tmp_path: Path) -> None:
        inventory = await collect_inventory(_registry(tmp_path, with_memory=False))
        payload: dict[str, Any] = inventory.to_dict()
        assert payload["gaps"] == ["memory", *PLATFORM_GAPS]
        assert payload["evidence"]["memory"]["status"] == "UNAVAILABLE"
        assert payload["evidence"]["memory"]["value"] is None

    async def test_evidence_snapshot_is_immutable(self, tmp_path: Path) -> None:
        inventory = await collect_inventory(_registry(tmp_path))
        with pytest.raises(TypeError):
            inventory.evidence["os"] = Evidence.unavailable("os", "x", "y")  # type: ignore[index]

    async def test_repeated_collection_is_stable(self, tmp_path: Path) -> None:
        registry = _registry(tmp_path)
        first = await collect_inventory(registry)
        second = await collect_inventory(registry)
        assert set(first.gaps) == set(second.gaps)

    def test_tool_name_prefix_is_consistent(self) -> None:
        assert tool_name_for("disk_usage") == "host.disk_usage"
        assert tool_name_for("load") == "host.load"
