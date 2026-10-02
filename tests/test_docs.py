"""Guards that keep the documentation honest about what actually exists.

NEXUS's whole premise is that it must not claim more than it can prove. That rule
applies to this repository's own docs: a README instruction that cannot be run is
a lie, even a well-intentioned one. Issue #1 shipped a `make eval` target pointing
at a module that never existed. These tests make that class of bug impossible to
merge.
"""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"
README = ROOT / "README.md"

PYTHON_M_REF = re.compile(r"python -m (nexus[\w.]*)")
MAKE_TARGET_REF = re.compile(r"(?:^make |`make )([a-zA-Z0-9_-]+)", re.MULTILINE)
MAKE_TARGET_DECL = re.compile(r"^([a-zA-Z0-9_-]+):", re.MULTILINE)
LAYOUT_ENTRY = re.compile(r"^[├└]──\s+(\w+)/", re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_makefile_python_module_references_are_importable() -> None:
    """Every `python -m nexus...` in the Makefile must resolve to a real module."""
    referenced = set(PYTHON_M_REF.findall(_read(MAKEFILE)))
    unresolvable = [ref for ref in sorted(referenced) if importlib.util.find_spec(ref) is None]
    assert not unresolvable, f"Makefile invokes modules that do not exist: {unresolvable}"


def test_readme_make_targets_exist() -> None:
    """Every `make <target>` shown in the README must be a declared Makefile target."""
    documented = set(MAKE_TARGET_REF.findall(_read(README)))
    declared = set(MAKE_TARGET_DECL.findall(_read(MAKEFILE)))
    unknown = sorted(documented - declared)
    assert not unknown, f"README documents make targets that do not exist: {unknown}"


def test_readme_project_layout_matches_source_tree() -> None:
    """The README's documented package layout must match `src/nexus/` on disk."""
    documented = set(LAYOUT_ENTRY.findall(_read(README)))
    actual = {
        path.name
        for path in (ROOT / "src" / "nexus").iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }
    assert documented, "expected to parse a package layout out of the README"
    assert actual <= documented, (
        f"undocumented packages in src/nexus: {sorted(actual - documented)}"
    )
