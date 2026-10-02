"""Read-only observation tools for the local host.

Every tool in this module is `READ_ONLY`: it inspects and reports, and cannot
change anything. That is not a stylistic choice. The default execution mode is
`READ_ONLY`, and observation is the only thing NEXUS may do until an operator
explicitly enables more.

None of these probes raise on failure. A host that cannot be reached yields
`EvidenceStatus.UNAVAILABLE` with the reason attached, because "the probe failed"
and "the value is fine" must never look the same to the reasoning layer.

Paths that differ by platform (`/proc/...` on Linux, nothing on Windows) are
constructor arguments rather than module constants, so the parsing logic is
testable on any platform.
"""

import os
import platform
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from nexus.tools.base import ToolDefinition, ToolRegistry
from nexus.tools.evidence import Evidence
from nexus.tools.permissions import PermissionClass

Probe = Callable[[], Evidence]


def _disk_usage_probe(path: str = "/") -> Evidence:
    """Filesystem usage for `path`.

    `/` is the interesting target on a homelab: a root filesystem at 100% is the
    single most common cause of a service that looks alive but stops accepting
    connections.
    """
    source = f"shutil.disk_usage({path!r})"
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return Evidence.unavailable("disk_usage", source, f"{type(exc).__name__}: {exc}")

    total = usage.total or 1
    return Evidence.observed_value(
        "disk_usage",
        source,
        {
            "path": path,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_pct": round(usage.used / total * 100, 2),
        },
    )


def _parse_meminfo(text: str, source: str) -> Evidence:
    """Parse `/proc/meminfo`-shaped `key: value kB` lines into bytes.

    Split out from the file read so the parsing is testable without depending on
    the machine running the tests.
    """
    fields: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        name, _, remainder = line.partition(":")
        parts = remainder.split()
        if not parts:
            continue
        try:
            amount = int(parts[0])
        except ValueError:
            continue
        fields[name.strip()] = amount * 1024 if parts[1:] == ["kB"] else amount

    if not fields:
        return Evidence.unavailable("memory", source, "no parsable fields found")

    total = fields.get("MemTotal")
    available = fields.get("MemAvailable")
    if total is None or available is None:
        return Evidence.unavailable(
            "memory", source, "MemTotal or MemAvailable missing from meminfo"
        )

    used = total - available
    return Evidence.observed_value(
        "memory",
        source,
        {
            "total_bytes": total,
            "available_bytes": available,
            "used_bytes": used,
            "used_pct": round(used / total * 100, 2),
        },
    )


def _memory_probe(meminfo_path: str = "/proc/meminfo") -> Evidence:
    source = f"read({meminfo_path})"
    try:
        text = Path(meminfo_path).read_text(encoding="utf-8")
    except OSError as exc:
        return Evidence.unavailable("memory", source, f"{type(exc).__name__}: {exc}")
    return _parse_meminfo(text, source)


def _os_probe() -> Evidence:
    source = "platform.*"
    try:
        value: dict[str, Any] = {
            "hostname": platform.node(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        }
    except OSError as exc:
        return Evidence.unavailable("os", source, f"{type(exc).__name__}: {exc}")
    return Evidence.observed_value("os", source, value)


def _load_probe() -> Evidence:
    """Load average, where the platform exposes it.

    `os.getloadavg` exists on Unix and is absent on Windows, so it is looked up
    dynamically. That keeps the module importable, and the probe honest, on both.
    """
    source = "os.getloadavg()"
    getter = getattr(os, "getloadavg", None)
    if getter is None:
        return Evidence.unavailable("load", source, "not available on this platform")
    try:
        one, five, fifteen = getter()
    except OSError as exc:
        return Evidence.unavailable("load", source, f"{type(exc).__name__}: {exc}")
    return Evidence.observed_value("load", source, {"1m": one, "5m": five, "15m": fifteen})


def _cpu_count_probe() -> Evidence:
    source = "os.cpu_count()"
    count = os.cpu_count()
    if count is None:
        return Evidence.unavailable("cpu_count", source, "os.cpu_count() returned None")
    return Evidence.observed_value("cpu_count", source, {"logical_cpus": count})


NO_PARAMETERS: Mapping[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}


def _as_tool(name: str, description: str, probe: Probe) -> ToolDefinition:
    """Wrap a synchronous probe as an async READ_ONLY tool handler.

    The handler returns the `Evidence` record itself rather than a serialized
    payload. Serialization belongs at the API boundary; converting here and back
    again downstream would only add a place for evidence to be lost.
    """

    async def handler(_arguments: Mapping[str, Any]) -> Evidence:
        return probe()

    return ToolDefinition(
        name=name,
        description=description,
        permission_class=PermissionClass.READ_ONLY,
        handler=handler,
        parameters=NO_PARAMETERS,
    )


def host_tool_definitions(
    *,
    root_path: str = "/",
    meminfo_path: str = "/proc/meminfo",
) -> list[ToolDefinition]:
    """The read-only host observation tools, built with injectable probe paths."""
    return [
        _as_tool(
            "host.disk_usage",
            "Report filesystem total, used and free bytes for a mount point.",
            lambda: _disk_usage_probe(root_path),
        ),
        _as_tool(
            "host.memory",
            "Report total, available and used memory in bytes.",
            lambda: _memory_probe(meminfo_path),
        ),
        _as_tool(
            "host.os",
            "Report hostname, OS, kernel release and CPU architecture.",
            _os_probe,
        ),
        _as_tool(
            "host.load",
            "Report 1/5/15 minute load averages where the OS exposes them.",
            _load_probe,
        ),
        _as_tool("host.cpu_count", "Report the number of logical CPUs.", _cpu_count_probe),
    ]


def register_host_tools(
    registry: ToolRegistry,
    *,
    root_path: str = "/",
    meminfo_path: str = "/proc/meminfo",
) -> ToolRegistry:
    """Register every read-only host tool. Mutates and returns `registry`."""
    for definition in host_tool_definitions(root_path=root_path, meminfo_path=meminfo_path):
        registry.register(definition)
    return registry


__all__ = [
    "Probe",
    "host_tool_definitions",
    "register_host_tools",
]
