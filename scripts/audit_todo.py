"""Fail when source files contain unfinished work markers or Python ellipsis stubs."""

from __future__ import annotations

import ast
import re
import sys
import tokenize
from io import StringIO
from pathlib import Path

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
        "htmlcov",
        "outputs",
    }
)
SOURCE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".c",
        ".cpp",
        ".go",
        ".h",
        ".hpp",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".py",
        ".rs",
        ".sh",
        ".ts",
        ".tsx",
    }
)
WORK_MARKER = re.compile(r"\b(?:TO" + "DO|FIX" + "ME)\b", re.IGNORECASE)
COMMENT_PREFIXES: tuple[str, ...] = ("#", "//", "/*", "*", "<!--", "--")


def _source_files(root: Path) -> list[Path]:
    """Return auditable source files outside generated directories."""
    return [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SOURCE_SUFFIXES
        and not any(part in EXCLUDED_DIRS or part.startswith("pytest_temp") for part in path.parts)
    ]


def _python_issues(path: Path, source: str) -> list[tuple[int, str]]:
    """Find Python comment markers and executable ellipsis placeholders."""
    issues: list[tuple[int, str]] = []
    try:
        tokens = tokenize.generate_tokens(StringIO(source).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT and WORK_MARKER.search(token.string):
                issues.append((token.start[0], "unfinished comment marker"))
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, tokenize.TokenError) as exc:
        return [(getattr(exc, "lineno", 1) or 1, f"cannot audit invalid Python: {exc}")]
    if path.suffix != ".pyi":
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and node.value.value is Ellipsis
            ):
                issues.append((node.lineno, "standalone ellipsis placeholder"))
    return issues


def _other_issues(source: str) -> list[tuple[int, str]]:
    """Find work markers in common non-Python comment forms."""
    issues: list[tuple[int, str]] = []
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(COMMENT_PREFIXES) and WORK_MARKER.search(stripped):
            issues.append((number, "unfinished comment marker"))
    return issues


def main() -> int:
    """Run the source-integrity audit."""
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    violations: list[str] = []
    for path in _source_files(root):
        source = path.read_text(encoding="utf-8", errors="replace")
        issues = _python_issues(path, source) if path.suffix == ".py" else _other_issues(source)
        relative = path.relative_to(root)
        violations.extend(f"{relative}:{line}: {message}" for line, message in issues)
    if violations:
        print("[audit-todo] FAIL")
        print("\n".join(violations))
        return 1
    print("[audit-todo] PASS: no unfinished work markers or ellipsis stubs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
