import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config as config_module  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway copy of the real register, with config pointed at it.

    Tests run against the real 380-row workbook rather than a toy fixture: the
    invariants that matter (no rows lost, no columns reordered, gap count stable)
    are only meaningful at real size and with real messy values.
    """
    source = Path(__file__).resolve().parent.parent / "data" / "Zeres_MID_Register.xlsx"
    if not source.exists():
        pytest.skip("register not built yet — run: python -m migrate.migrate_tracker")

    register_path = tmp_path / "Zeres_MID_Register.xlsx"
    shutil.copy2(source, register_path)
    backup_dir = tmp_path / "backups"

    config_module.override_config(register_path=register_path, backup_dir=backup_dir, keep_backups=30)
    yield register_path
    config_module.reset_config()
