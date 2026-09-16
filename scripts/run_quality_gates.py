"""Phase quality gate runner.

Usage:
    python scripts/run_quality_gates.py [--skip-mypy]

Sets project-local TEMP/TMP so pytest tmp_path does not hit Windows sandbox
permission errors, then runs:

1. ruff check src tests scripts
2. pytest -q -p no:cacheprovider -o addopts=''
3. mypy src scripts
4. git diff --check
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(title: str, command: list[str]) -> int:
    print(f"\n=== {title} ===")
    print("+", " ".join(command))
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print(f"FAILED: {title} (exit {result.returncode})")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-mypy", action="store_true", help="skip mypy run")
    args = parser.parse_args()

    tmp = ROOT / ".artifacts" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(tmp)
    os.environ["TMP"] = str(tmp)

    exit_codes: list[int] = []
    ruff_cmd = [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"]
    exit_codes.append(_run("Ruff", ruff_cmd))
    exit_codes.append(
        _run(
            "Pytest",
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts="],
        )
    )
    if not args.skip_mypy:
        exit_codes.append(_run("Mypy", [sys.executable, "-m", "mypy", "src", "scripts"]))
    exit_codes.append(_run("Git diff check", ["git", "diff", "--check"]))

    failed = [code for code in exit_codes if code != 0]
    if failed:
        print(f"\nQuality gates failed: {len(failed)} step(s) failed")
        return 1
    print("\nAll quality gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
