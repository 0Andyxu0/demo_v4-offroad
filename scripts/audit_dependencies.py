"""Fail when Python source imports an undeclared third-party distribution."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

SOURCE_DIRS: tuple[str, ...] = ("src", "tests", "demo", "scripts")
IMPORT_ALIASES: dict[str, str] = {
    "PIL": "pillow",
    "PyQt5": "pyqt5",
    "affine": "affine",
    "geopandas": "geopandas",
    "h3": "h3",
    "numpy": "numpy",
    "pandas": "pandas",
    "pyarrow": "pyarrow",
    "pytest": "pytest",
    "rasterio": "rasterio",
    "shapely": "shapely",
    "yaml": "pyyaml",
}
EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        ".artifacts",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
        "outputs",
    }
)


def _normalize(name: str) -> str:
    """Normalize a distribution name using Python packaging conventions."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _distribution_name(requirement: str) -> str:
    """Extract a distribution name from a PEP 508-style requirement."""
    return _normalize(re.split(r"[\s<>=!~;\[]", requirement.strip(), maxsplit=1)[0])


def _declared(root: Path) -> set[str]:
    """Read core and optional dependencies from pyproject.toml."""
    path = root / "pyproject.toml"
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    project = payload.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml must contain [project]")
    requirements: list[str] = []
    raw_dependencies = project.get("dependencies", [])
    if isinstance(raw_dependencies, list):
        requirements.extend(str(value) for value in raw_dependencies)
    optional = project.get("optional-dependencies", {})
    if isinstance(optional, dict):
        for values in optional.values():
            if isinstance(values, list):
                requirements.extend(str(value) for value in values)
    return {_distribution_name(value) for value in requirements}


def _python_files(root: Path) -> list[Path]:
    """Return project Python files from the declared source roots."""
    files: list[Path] = []
    for directory in SOURCE_DIRS:
        base = root / directory
        if not base.exists():
            continue
        files.extend(
            path
            for path in base.rglob("*.py")
            if not any(
                part in EXCLUDED_DIRS or part.startswith("pytest_temp") for part in path.parts
            )
        )
    return files


def _imports(root: Path) -> set[str]:
    """Collect absolute top-level imports and fail closed on invalid Python."""
    modules: set[str] = set()
    for path in _python_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".", maxsplit=1)[0])
    return modules


def main() -> int:
    """Run the dependency declaration audit."""
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    try:
        declared = _declared(root)
        imported = _imports(root)
    except (OSError, SyntaxError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"[audit-dependencies] FAIL: {exc}")
        return 1
    local = {
        _normalize(name)
        for name in {"demo", "h3_offroad_planner", "scripts", "tests"}
    }
    local.update(_normalize(path.stem) for path in _python_files(root))
    third_party = {
        _normalize(IMPORT_ALIASES.get(module, module))
        for module in imported
        if module not in sys.stdlib_module_names and _normalize(module) not in local
    }
    missing = sorted(third_party - declared)
    if missing:
        print("[audit-dependencies] FAIL: undeclared imports: " + ", ".join(missing))
        return 1
    unused = sorted(declared - third_party)
    print(
        "[audit-dependencies] PASS: all imports declared"
        + (f"; review unused declarations: {', '.join(unused)}" if unused else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
