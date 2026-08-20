"""config.toml + .env loading.

Paths in config.toml may be relative; they resolve against the project root so
the app behaves the same however it is launched.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.toml"


@dataclass(frozen=True)
class Config:
    register_path: Path
    backup_dir: Path
    keep_backups: int
    drive_root: Path
    max_concurrent: int
    timeout_seconds: int
    max_retries: int
    user_agent: str
    host: str
    port: int
    open_browser: bool

    @property
    def technical_root(self) -> Path:
        """<DriveRoot>/Technical — the top of the filing tree."""
        return self.drive_root / "Technical"


def _resolve(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path)


def _read_config(path: Path) -> dict:
    """Parse config.toml, tolerating however Windows saved it.

    This file gets edited by hand on Windows, and the two obvious ways of doing
    that both produce something tomllib refuses:

      - PowerShell's `Set-Content -Encoding UTF8` writes a byte-order mark, and
        TOML has no idea what to do with one ("Invalid statement, line 1")
      - saving as ANSI turns any non-ASCII character in a comment into a byte
        that is not valid UTF-8 at all

    Neither is the user's fault, and both would otherwise stop the app dead over
    a comment they never touched. So: drop a BOM if present, and fall back to
    cp1252 if the bytes are not UTF-8.
    """
    if not path.exists():
        return {}

    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")

    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(
            f"Could not read {path.name}: {exc}\n\n"
            f"On Windows a path needs SINGLE quotes, because TOML treats \\ as an escape:\n"
            f"    root = 'G:\\Shared drives\\ZERES Drive\\...'   correct\n"
            f'    root = "G:\\Shared drives\\ZERES Drive\\..."   fails\n'
        ) from exc


def _load_dotenv() -> None:
    """Minimal .env reader — no secrets are required today, but the hook exists."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_override: Config | None = None


def get_config() -> Config:
    """The active configuration. Cached; tests can replace it via override_config()."""
    global _cached
    if _override is not None:
        return _override
    if _cached is None:
        _cached = _build_config()
    return _cached


_cached: Config | None = None


def _build_config() -> Config:
    _load_dotenv()
    raw = _read_config(CONFIG_PATH)

    storage = raw.get("storage", {})
    drive = raw.get("drive", {})
    dl = raw.get("downloader", {})
    server = raw.get("server", {})

    # Environment wins over config.toml, so one machine can differ without a diff.
    register = os.environ.get("ZERES_REGISTER_PATH") or storage.get(
        "register_path", "data/Zeres_MID_Register.xlsx"
    )
    drive_root = os.environ.get("ZERES_DRIVE_ROOT") or drive.get("root", "data/drive")

    return Config(
        register_path=_resolve(register),
        backup_dir=_resolve(storage.get("backup_dir", "backups")),
        keep_backups=int(storage.get("keep_backups", 30)),
        drive_root=_resolve(drive_root),
        max_concurrent=int(dl.get("max_concurrent", 6)),
        timeout_seconds=int(dl.get("timeout_seconds", 60)),
        max_retries=int(dl.get("max_retries", 4)),
        user_agent=dl.get("user_agent", "ZeresMIDRegister/1.0"),
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 8765)),
        open_browser=bool(server.get("open_browser", True)),
    )


def override_config(**kwargs) -> Config:
    """Test hook: replace the active config with a modified copy."""
    global _override
    base = _override or get_config()
    _override = Config(**{**base.__dict__, **kwargs})
    return _override


def reset_config() -> None:
    """Test hook: drop any override and re-read config.toml."""
    global _override, _cached
    _override = None
    _cached = None
