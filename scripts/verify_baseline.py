"""Run the complete local technical-baseline acceptance gate."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT: Path = Path(__file__).resolve().parents[1]
DOC_ROOT: Path = ROOT / "docs" / "code" / "h3-offroad-planner"
ARTIFACT_ROOT: Path = ROOT / ".artifacts" / "quality"
RUN_ROOT: Path = ARTIFACT_ROOT / "run"
COVERAGE_PATH: Path = ARTIFACT_ROOT / "coverage.json"
SUMMARY_PATH: Path = ARTIFACT_ROOT / "gate-summary.json"
STATEMENT_THRESHOLD: float = 80.0
BRANCH_THRESHOLD: float = 70.0
ACTIVE_DOCS: tuple[str, ...] = (
    "spec.md",
    "architecture.md",
    "api-design.md",
    "test-specs.md",
    "gate1-design-score.md",
    "pm-project-initiation-status.md",
    "coverage-gap-analysis.md",
    "closed-loop-contract.md",
)
FORBIDDEN_ACTIVE_SYMBOLS: tuple[str, ...] = (
    "PBSFleetCoordinator",
    "QThread",
)
FORBIDDEN_ACTIVE_CLAIMS: tuple[str, ...] = (
    "LegacyDeterministicParetoPlanner` 保留",
    "旧图合同适配器；显式使用",
    "global_planner: NSGAII` 仍可",
)
AUDIT_SCRIPTS: tuple[str, ...] = (
    "audit_todo.py",
    "audit_dependencies.py",
    "audit_gitignore.py",
)
QT_SMOKE_CODE: str = """
import os
from PyQt5.QtCore import QCoreApplication, QTimer, Qt
from PyQt5.QtWidgets import QApplication

QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
app = QApplication([])
from PyQt5.QtWebEngineWidgets import QWebEngineProfile
from h3_offroad_planner.desktop_map import DesktopMapView

cache_root = os.environ["H3_BASELINE_QT_CACHE"]
profile = QWebEngineProfile.defaultProfile()
profile.setCachePath(cache_root)
profile.setPersistentStoragePath(cache_root)
view = DesktopMapView()
state = {"loaded": False}

def finished(ok: bool) -> None:
    state["loaded"] = ok
    view.close()
    view.deleteLater()
    QTimer.singleShot(0, app.quit)

view.loadFinished.connect(finished)
QTimer.singleShot(15000, app.quit)
app.exec_()
app.processEvents()
raise SystemExit(0 if state["loaded"] else 1)
"""


class GateError(RuntimeError):
    """Raised when a baseline acceptance gate fails."""


def _run(command: list[str], *, environment: dict[str, str] | None = None) -> None:
    """Run one visible gate command and fail closed on a nonzero exit."""
    print(f"\n[baseline] running: {' '.join(command)}", flush=True)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        raise GateError(
            f"command failed with exit code {completed.returncode}: {' '.join(command)}"
        )


def _prepare_artifacts() -> None:
    """Remove only the controlled current-run directory and stale final evidence."""
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    if RUN_ROOT.exists():
        shutil.rmtree(RUN_ROOT)
    for path in (COVERAGE_PATH, SUMMARY_PATH):
        path.unlink(missing_ok=True)
    RUN_ROOT.mkdir(parents=True)


def _gate_environment() -> dict[str, str]:
    """Redirect tool caches and intermediate coverage data into the controlled run."""
    environment = os.environ.copy()
    environment["COVERAGE_FILE"] = str(RUN_ROOT / ".coverage")
    environment["MYPY_CACHE_DIR"] = str(RUN_ROOT / "mypy-cache")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["RUFF_CACHE_DIR"] = str(RUN_ROOT / "ruff-cache")
    return environment


def _finalize_artifacts() -> None:
    """Remove transient run data so only final evidence remains."""
    if RUN_ROOT.exists():
        shutil.rmtree(RUN_ROOT)


def _json_number(payload: dict[str, object], key: str) -> int:
    """Read one non-negative integer coverage counter."""
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GateError(f"coverage totals.{key} must be a non-negative integer")
    return value


def _coverage_percent(covered: int, total: int, label: str) -> float:
    """Return a percentage while rejecting an empty coverage denominator."""
    if total <= 0:
        raise GateError(f"coverage {label} denominator must be positive")
    return covered * 100.0 / total


def _check_coverage() -> tuple[float, float]:
    """Validate independent statement and branch thresholds from coverage JSON."""
    try:
        raw = json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot read coverage evidence: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("totals"), dict):
        raise GateError("coverage JSON must contain an object-valued totals field")
    totals = cast(dict[str, object], raw["totals"])
    statements = _json_number(totals, "num_statements")
    covered_lines = _json_number(totals, "covered_lines")
    branches = _json_number(totals, "num_branches")
    covered_branches = _json_number(totals, "covered_branches")
    statement_percent = _coverage_percent(covered_lines, statements, "statements")
    branch_percent = _coverage_percent(covered_branches, branches, "branches")
    if statement_percent < STATEMENT_THRESHOLD:
        raise GateError(
            f"statement coverage {statement_percent:.2f}% is below "
            f"{STATEMENT_THRESHOLD:.2f}%"
        )
    if branch_percent < BRANCH_THRESHOLD:
        raise GateError(
            f"branch coverage {branch_percent:.2f}% is below {BRANCH_THRESHOLD:.2f}%"
        )
    return statement_percent, branch_percent


def _check_active_docs() -> None:
    """Reject retired active claims while allowing explicit historical statements."""
    for name in ACTIVE_DOCS:
        path = DOC_ROOT / name
        text = path.read_text(encoding="utf-8")
        found_symbols = [symbol for symbol in FORBIDDEN_ACTIVE_SYMBOLS if symbol in text]
        found_claims = [claim for claim in FORBIDDEN_ACTIVE_CLAIMS if claim in text]
        if found_symbols or found_claims:
            found = ", ".join([*found_symbols, *found_claims])
            raise GateError(f"{name} contains retired active claims: {found}")


def _check_adrs() -> None:
    """Require unique ADR ids and matching filename/title identifiers."""
    ids: list[str] = []
    for path in sorted((DOC_ROOT / "adr").glob("ADR-*.md")):
        match = re.fullmatch(r"ADR-(\d{3})-.+\.md", path.name)
        if match is None:
            raise GateError(f"malformed ADR filename: {path.name}")
        adr_id = match.group(1)
        ids.append(adr_id)
        heading = path.read_text(encoding="utf-8").splitlines()[0]
        if not heading.startswith(f"# ADR-{adr_id}"):
            raise GateError(f"ADR heading does not match filename: {path.name}")
    duplicates = sorted(adr_id for adr_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise GateError(f"duplicate ADR identifiers: {', '.join(duplicates)}")


def _check_cl_traceability() -> None:
    """Require exactly one pytest function for every CL-001 through CL-040."""
    counts: Counter[int] = Counter()
    pattern = re.compile(r"^def test_cl(\d{3})(?:_|\()", re.MULTILINE)
    for path in (ROOT / "tests").glob("test_*.py"):
        counts.update(int(value) for value in pattern.findall(path.read_text(encoding="utf-8")))
    missing = [value for value in range(1, 41) if counts[value] == 0]
    duplicate = [value for value in range(1, 41) if counts[value] > 1]
    outside = sorted(value for value in counts if value < 1 or value > 40)
    if missing or duplicate or outside:
        raise GateError(
            "CL traceability invalid: "
            f"missing={missing}, duplicate={duplicate}, outside={outside}"
        )


def _git_output(command: list[str]) -> str:
    """Run a read-only Git query and return UTF-8 output."""
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise GateError(f"Git query failed: {' '.join(command)}")
    return completed.stdout


def _configured_map_token(required: bool) -> tuple[str, str]:
    """Validate an optional ignored private map config and return token/source."""
    environment_token = os.environ.get("H3_OFFROAD_TIANDITU_TOKEN", "").strip()
    private_path = ROOT / "configs" / "map.private.yaml"
    token = environment_token
    source = "environment" if token else "absent-optional"
    if private_path.is_file():
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "configs/map.private.yaml"],
            cwd=ROOT,
            check=False,
        )
        if ignored.returncode != 0:
            raise GateError("configs/map.private.yaml must be ignored by Git")
        match = re.search(
            r"(?m)^\s*token\s*:\s*['\"]?([^'\"#\r\n]+)['\"]?\s*(?:#.*)?$",
            private_path.read_text(encoding="utf-8"),
        )
        local_token = match.group(1).strip() if match else ""
        if not token and local_token:
            token = local_token
            source = "local_config"
    if required and not token:
        raise GateError("a private map token is required for this optional gate mode")
    if token:
        token_bytes = token.encode()
        leaked: list[str] = []
        for relative in _git_output(["git", "ls-files", "-z"]).split("\0"):
            if not relative:
                continue
            path = ROOT / relative
            if path.is_file() and token_bytes in path.read_bytes():
                leaked.append(relative)
        if leaked:
            raise GateError(f"private map token appears in tracked files: {', '.join(leaked)}")
    return token, source


def _check_online_map(token: str) -> None:
    """Fetch one Tianditu tile only when the caller explicitly requests it."""
    if not token:
        raise GateError("--online-map requires a configured private map token")
    url = (
        "https://t0.tianditu.gov.cn/img_w/wmts"
        "?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=img&STYLE=default"
        f"&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX=1&TILEROW=0&TILECOL=1&tk={quote(token)}"
    )
    request = Request(url, headers={"User-Agent": "demo-v1-baseline-gate"})
    try:
        with urlopen(request, timeout=10) as response:
            status = response.status
    except OSError as exc:
        raise GateError(f"online map check failed: {exc}") from exc
    if status != 200:
        raise GateError(f"online map check returned HTTP {status}")


def _run_qt_smoke() -> None:
    """Load the real desktop map with the native Windows Qt platform."""
    environment = os.environ.copy()
    environment["H3_BASELINE_QT_CACHE"] = str(RUN_ROOT / "qt-webengine")
    environment["QT_QPA_PLATFORM"] = "windows"
    environment["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --no-sandbox"
    environment["QTWEBENGINE_DISABLE_GPU_SHADER_DISK_CACHE"] = "1"
    environment["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    existing_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + existing_path if existing_path else ""
    )
    _run([sys.executable, "-c", QT_SMOKE_CODE], environment=environment)


def _run_static_checks(environment: dict[str, str]) -> None:
    """Run style, type, diff, document, ADR, CL, and audit gates."""
    _run(
        [sys.executable, "-m", "ruff", "check", "src", "tests", "demo", "scripts"],
        environment=environment,
    )
    _run([sys.executable, "-m", "mypy", "src", "scripts"], environment=environment)
    _run(["git", "diff", "--check"], environment=environment)
    _run(["git", "diff", "--cached", "--check"], environment=environment)
    _check_active_docs()
    _check_adrs()
    _check_cl_traceability()
    for script in AUDIT_SCRIPTS:
        _run(
            [sys.executable, str(ROOT / "scripts" / script), str(ROOT)],
            environment=environment,
        )


def _write_summary(
    status: str,
    *,
    statement_percent: float | None = None,
    branch_percent: float | None = None,
    map_token_source: str = "unchecked",
    error: str | None = None,
) -> None:
    """Persist the latest gate result without secrets or transient test data."""
    payload: dict[str, object] = {
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "statement_threshold": STATEMENT_THRESHOLD,
        "branch_threshold": BRANCH_THRESHOLD,
        "map_token_source": map_token_source,
        "qt_webengine_smoke": status == "pass",
    }
    if statement_percent is not None:
        payload["statement_percent"] = round(statement_percent, 2)
    if branch_percent is not None:
        payload["branch_percent"] = round(branch_percent, 2)
    if error is not None:
        payload["error"] = error
    SUMMARY_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_args() -> argparse.Namespace:
    """Parse optional local-only map checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-private-map",
        action="store_true",
        help="require an environment or ignored local Tianditu token",
    )
    parser.add_argument(
        "--online-map",
        action="store_true",
        help="perform one live Tianditu tile request; implies --require-private-map",
    )
    return parser.parse_args()


def main() -> int:
    """Execute the local acceptance workflow and return a process exit code."""
    args = _parse_args()
    _prepare_artifacts()
    environment = _gate_environment()
    map_source = "unchecked"
    try:
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                f"--basetemp={RUN_ROOT / 'pytest'}",
                "--cov=h3_offroad_planner",
                "--cov-branch",
                "--cov-report=term-missing",
                f"--cov-report=json:{COVERAGE_PATH}",
            ],
            environment=environment,
        )
        statement_percent, branch_percent = _check_coverage()
        _run_static_checks(environment)
        token, map_source = _configured_map_token(
            bool(args.require_private_map or args.online_map)
        )
        if args.online_map:
            _check_online_map(token)
        _run_qt_smoke()
    except (GateError, OSError) as exc:
        _finalize_artifacts()
        _write_summary("fail", map_token_source=map_source, error=str(exc))
        print(f"\n[baseline] FAIL: {exc}", file=sys.stderr)
        return 1
    _finalize_artifacts()
    _write_summary(
        "pass",
        statement_percent=statement_percent,
        branch_percent=branch_percent,
        map_token_source=map_source,
    )
    print(
        "\n[baseline] PASS: "
        f"statement={statement_percent:.2f}%, branch={branch_percent:.2f}%, "
        "CL-001..040 unique, ADR ids unique, audits pass, QWebEngine loaded, "
        f"map_token={map_source}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
