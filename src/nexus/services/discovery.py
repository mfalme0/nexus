"""Phase 2: local host discovery.

Discovery assembles a snapshot of what is actually running on a host, together
with the evidence that proves each field. The snapshot keeps its gaps: a field
that could not be observed stays absent and is backed by an UNAVAILABLE `Evidence`
record rather than being filled with a plausible default. Downstream phases must
be able to tell "this platform has no load average" apart from "load is zero".

Probes are invoked through `ToolExecutor` rather than called directly, so
discovery exercises the same permission check the agent will. That means discovery
cannot accidentally become a way around the policy: a probe that is not on the
allowlist yields no evidence instead of a result.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from nexus.tools.base import ToolExecutor, ToolRegistry, ToolResult
from nexus.tools.evidence import Evidence, EvidenceStatus
from nexus.tools.host import register_host_tools
from nexus.tools.permissions import PermissionPolicy

# Inventory keys, in the stable order they appear in reports.
INVENTORY_KEYS: tuple[str, ...] = ("os", "cpu_count", "memory", "disk_usage", "load")

_TOOL_PREFIX = "host."


def tool_name_for(probe_key: str) -> str:
    """The registered tool name that produces `probe_key`."""
    return f"{_TOOL_PREFIX}{probe_key}"


@dataclass(frozen=True, slots=True)
class HostInventory:
    """A point-in-time view of one host, with the evidence supporting each field.

    `observed_at` is stamped once for the whole snapshot rather than per field, so
    a conclusion spanning several fields refers to one coherent moment in time.
    """

    hostname: str | None
    observed_at: datetime
    evidence: Mapping[str, Evidence]

    @property
    def complete(self) -> bool:
        """True when every probe in the inventory succeeded.

        Deliberately not named `healthy`. Full coverage means NEXUS is entitled to
        make claims about this host; it says nothing about whether they are good
        news.
        """
        return bool(self.evidence) and all(item.observed for item in self.evidence.values())

    @property
    def gaps(self) -> tuple[str, ...]:
        """Keys that could not be observed, in inventory order."""
        return tuple(key for key in INVENTORY_KEYS if not self._is_observed(key))

    @property
    def coverage_ratio(self) -> float:
        """Fraction of collected probes that returned usable evidence."""
        if not self.evidence:
            return 0.0
        return sum(1 for item in self.evidence.values() if item.observed) / len(self.evidence)

    def value(self, key: str) -> Mapping[str, Any] | None:
        """The observed payload for `key`, or None when missing or unavailable."""
        item = self.evidence.get(key)
        if item is None or item.status is not EvidenceStatus.OBSERVED:
            return None
        return item.value

    def claims(self) -> tuple[str, ...]:
        """One quotable sentence per probe, gaps included as explicit non-claims."""
        return tuple(
            self.evidence[key].as_claim() for key in INVENTORY_KEYS if key in self.evidence
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializable form, for the API layer. Gaps stay visible here too."""
        return {
            "hostname": self.hostname,
            "observed_at": self.observed_at.isoformat(),
            "complete": self.complete,
            "coverage_ratio": round(self.coverage_ratio, 4),
            "gaps": list(self.gaps),
            "evidence": {
                key: {
                    "status": str(item.status),
                    "source": item.source,
                    "observed_at": item.observed_at.isoformat(),
                    "value": item.value,
                    "detail": item.detail,
                    "claim": item.as_claim(),
                }
                for key, item in self.evidence.items()
            },
        }

    def _is_observed(self, key: str) -> bool:
        item = self.evidence.get(key)
        return item is not None and item.observed


def build_read_only_registry(
    *,
    root_path: str = "/",
    meminfo_path: str = "/proc/meminfo",
) -> ToolRegistry:
    """A registry preloaded with only the read-only observation tools.

    The execution mode is left at its default `READ_ONLY`, so anything registered
    later that is not itself READ_ONLY stays refused until an operator makes a
    deliberate decision.
    """
    return register_host_tools(
        ToolRegistry(PermissionPolicy()),
        root_path=root_path,
        meminfo_path=meminfo_path,
    )


def _coerce(probe_key: str, result: ToolResult) -> Evidence:
    """Normalize a tool outcome into an `Evidence` record, keeping the gap visible."""
    value = result.value
    if result.ok and isinstance(value, Evidence):
        return value
    detail = result.error or result.decision.reason
    return Evidence.unavailable(probe_key, "tool invocation", str(detail))


def _hostname_from(evidence: Evidence) -> str | None:
    if not evidence.observed or not evidence.value:
        return None
    raw = evidence.value.get("hostname")
    return str(raw) if raw else None


async def collect_inventory(
    registry: ToolRegistry,
    probes: Sequence[str] = INVENTORY_KEYS,
) -> HostInventory:
    """Run the read-only probes and assemble a `HostInventory` from the results.

    Probe failures are collected as UNAVAILABLE evidence instead of propagating,
    so one unreachable source cannot hide the state of everything else. A probe
    that is missing from the registry is reported the same way: discovery records
    the absence rather than pretending the key is absent from the host.
    """
    executor = ToolExecutor(registry)
    collected: dict[str, Evidence] = {}

    for probe_key in probes:
        result = await executor.invoke(tool_name_for(probe_key), {})
        collected[probe_key] = _coerce(probe_key, result)

    immutable: Mapping[str, Evidence] = MappingProxyType(collected)
    return HostInventory(
        hostname=_hostname_from(collected.get("os", Evidence.unavailable("os", "none", "absent"))),
        observed_at=datetime.now(UTC),
        evidence=immutable,
    )
