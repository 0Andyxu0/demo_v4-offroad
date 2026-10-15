"""Fail when the Git staging area contains sensitive paths or credential material."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SENSITIVE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".cer",
        ".crt",
        ".db",
        ".der",
        ".env",
        ".jks",
        ".key",
        ".keystore",
        ".p12",
        ".pem",
        ".pfx",
        ".sqlite",
        ".sqlite3",
    }
)
SENSITIVE_NAMES: frozenset[str] = frozenset(
    {
        ".env",
        ".env.development",
        ".env.local",
        ".env.production",
        ".netrc",
        "credentials.json",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
        "service-account.json",
        "service_account.json",
    }
)
TEXT_SUFFIXES: frozenset[str] = frozenset(
    {".cfg", ".conf", ".env", ".ini", ".json", ".md", ".py", ".toml", ".yaml", ".yml"}
)
PRIVATE_KEY_MARKER = "-----BEGIN " + "PRIVATE KEY-----"
CONFIG_CREDENTIAL_PATTERN = re.compile(
    r"(?im)^\s*(?:api[_-]?key|access[_-]?token|password|secret|token)\s*[:=]\s*"
    r"['\"]?(?!\$\{|<|example|replace|your_)[A-Za-z0-9_./+=-]{16,}"
)
PYTHON_CREDENTIAL_PATTERN = re.compile(
    r"(?im)^\s*(?:api[_-]?key|access[_-]?token|password|secret|token)\s*=\s*"
    r"(?P<quote>['\"])(?!\$\{|<|example|replace|your_)[^'\"\r\n]{16,}(?P=quote)"
)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a Git query with stable UTF-8 decoding."""
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _staged_paths(root: Path) -> list[str]:
    """Return added, copied, modified, or renamed paths from the index."""
    completed = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
    if completed.returncode != 0:
        raise RuntimeError("cannot query the Git staging area")
    return [line for line in completed.stdout.splitlines() if line]


def _staged_text(root: Path, relative: str) -> str:
    """Read a staged text blob without consulting the working tree."""
    completed = _git(root, "show", f":{relative}")
    if completed.returncode != 0:
        raise RuntimeError(f"cannot inspect staged file: {relative}")
    return completed.stdout


def main(argv: list[str] | None = None) -> int:
    """Run the sensitive-staging audit."""
    if argv is not None:
        target = argv[0] if argv else "."
    elif len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        target = sys.argv[1]
    else:
        target = "."
    root = Path(target).resolve()
    if root.is_file():
        root = root.parent
    elif not root.is_dir():
        root = Path(".").resolve()
    if _git(root, "rev-parse", "--show-toplevel").returncode != 0:
        print("[audit-gitignore] FAIL: target is not a Git repository")
        return 1
    violations: list[str] = []
    try:
        for relative in _staged_paths(root):
            path = Path(relative)
            name = path.name.lower()
            if name in SENSITIVE_NAMES or path.suffix.lower() in SENSITIVE_SUFFIXES:
                violations.append(f"{relative}: sensitive path")
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            content = _staged_text(root, relative)
            credential_pattern = (
                PYTHON_CREDENTIAL_PATTERN
                if path.suffix.lower() == ".py"
                else CONFIG_CREDENTIAL_PATTERN
            )
            if PRIVATE_KEY_MARKER in content or credential_pattern.search(content):
                violations.append(f"{relative}: credential-like content")
    except RuntimeError as exc:
        print(f"[audit-gitignore] FAIL: {exc}")
        return 1
    if violations:
        print("[audit-gitignore] FAIL")
        print("\n".join(violations))
        return 1
    print("[audit-gitignore] PASS: staged paths contain no sensitive material")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
