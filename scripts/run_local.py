"""Run this checkout with the default Python, without changing global installs.

Examples: python scripts/run_local.py cli --help
          python scripts/run_local.py desktop
          python scripts/run_local.py pytest tests/test_desktop_project.py -q
"""
from pathlib import Path
import os
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
os.environ['PYTHONPATH'] = str(ROOT / 'src') + (os.pathsep + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else '')


def main():
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python scripts/run_local.py {cli|desktop|pytest|verify} [args]')
    mode, args = sys.argv[1], sys.argv[2:]
    import h3_offroad_planner
    assert Path(h3_offroad_planner.__file__).resolve().is_relative_to(ROOT/'src')
    os.chdir(ROOT)
    if mode == 'cli':
        from h3_offroad_planner.cli import main as cli_main
        return cli_main(args)
    if mode == 'desktop':
        from h3_offroad_planner import desktop_client
        config=ROOT/'configs/manned_offroad.local.private.yaml'
        if not config.is_file():
            raise SystemExit(f'Local project config missing: {config}')
        # Keep production source at 986bd58; only this launcher selects the local project.
        desktop_client.DEFAULT_DELIVERY_PATH = config
        sys.argv=[sys.argv[0],*args]
        return desktop_client.run_desktop_client()
    if mode == 'pytest':
        import pytest
        return pytest.main(args)
    if mode == 'verify':
        sys.argv=[str(ROOT/'scripts/verify_manned_workspace.py'),*args]
        runpy.run_path(sys.argv[0],run_name='__main__')
        return 0
    raise SystemExit(f'Unknown mode: {mode}')


if __name__ == '__main__':
    raise SystemExit(main())
