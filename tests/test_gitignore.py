"""Tests for repository .gitignore rules and audit_gitignore compliance."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import audit_gitignore  # type: ignore[import-not-found]


def _check_ignore(paths: list[str]) -> set[str]:
    """Run git check-ignore --stdin on paths and return the set of ignored paths."""
    input_data = ("\n".join(paths) + "\n").encode("utf-8")
    proc = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        input=input_data,
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    stdout = proc.stdout.decode("utf-8", errors="replace")
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def test_audit_gitignore_script_passes() -> None:
    """audit_gitignore script should pass on the current repository without errors."""
    exit_code = audit_gitignore.main()
    assert exit_code == 0


def test_no_tracked_files_ignored() -> None:
    """None of the currently tracked files should be ignored by .gitignore."""
    git_files = subprocess.check_output(
        ["git", "ls-files"], cwd=ROOT, text=True, encoding="utf-8"
    ).splitlines()
    ignored = _check_ignore(git_files)
    assert ignored == set(), f"Tracked files incorrectly ignored: {ignored}"


def test_audit_sensitive_names_and_suffixes_ignored() -> None:
    """All sensitive names and suffixes audited by audit_gitignore must be in .gitignore."""
    # Test all SENSITIVE_NAMES
    names_to_test = list(audit_gitignore.SENSITIVE_NAMES)
    ignored_names = _check_ignore(names_to_test)
    missing_names = set(names_to_test) - ignored_names
    assert not missing_names, f"Sensitive names not ignored: {missing_names}"

    # Test all SENSITIVE_SUFFIXES
    suffixes_to_test = [f"dummy_secret{sfx}" for sfx in audit_gitignore.SENSITIVE_SUFFIXES]
    ignored_suffixes = _check_ignore(suffixes_to_test)
    missing_suffixes = set(suffixes_to_test) - ignored_suffixes
    assert not missing_suffixes, f"Sensitive suffixes not ignored: {missing_suffixes}"


def test_gis_large_binaries_and_sidecars_ignored() -> None:
    """GIS datasets, lock files, and sidecars must be ignored."""
    gis_paths = [
        "area.tif",
        "area.tiff",
        "elevation.dem",
        "cldas.nc",
        "cldas.nc4",
        "soil.h5",
        "soil.hdf",
        "dataset.parquet",
        "dataset.feather",
        "features.gpkg",
        "roads.shp",
        "roads.shx",
        "roads.dbf",
        "roads.prj",
        "roads.cpg",
        "roads.shp.xml",
        "roads.lock",
        "roads.sr.lock",
        "ortho.tfw",
        "ortho.wld",
        "ortho.jgw",
        "ortho.pgw",
        "geodb.gdb/",
        "boundary.kml",
        "boundary.kmz",
    ]
    ignored = _check_ignore(gis_paths)
    missing = set(gis_paths) - ignored
    assert not missing, f"GIS artifacts not ignored: {missing}"


def test_project_outputs_and_private_configs_ignored() -> None:
    """Outputs, artifacts, logs, and private configuration files must be ignored."""
    test_paths = [
        "outputs/route_plan.json",
        ".artifacts/test_log.txt",
        "logs/debug.log",
        "configs/manned_offroad.local.private.yaml",
        "configs/my_test.private.yml",
        "configs/custom.private.json",
        "configs/local_dev.local.yaml",
        "credentials.yaml",
        "secret.yaml",
        "secret.json",
        "token.json",
        "api_access.token",
        "id_rsa",
        "id_ed25519",
        ".netrc",
        ".cache/download",
        ".ipynb_checkpoints/analysis.ipynb",
    ]
    ignored = _check_ignore(test_paths)
    missing = set(test_paths) - ignored
    assert not missing, f"Project outputs / private configs not ignored: {missing}"
