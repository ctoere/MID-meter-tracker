"""Is the configured Drive folder actually the right folder?

The app writes evidence into a plain directory and lets Google Drive for desktop
sync it. That is deliberate — no OAuth, no cloud — but it has one failure mode:
point it at the wrong folder and everything appears to work. Files are written,
the UI says "stored", and nothing reaches Drive. You find out twenty documents
later.

So the path is checked at startup and surfaced in the UI, and the checks know
about the mistakes that actually happen rather than just "does it exist".
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePath

from .config import PROJECT_ROOT, Config, get_config

OK = "ok"
WARNING = "warning"
ERROR = "error"

#: Subfolders the register's own conventions expect below Technical.
EXPECTED = ("Chargers", "Meters")


@dataclass
class DriveStatus:
    level: str = OK
    root: str = ""
    technical: str = ""
    headline: str = ""
    details: list[str] = field(default_factory=list)
    fix: str = ""

    @property
    def ok(self) -> bool:
        return self.level == OK

    def as_dict(self) -> dict:
        return {"level": self.level, "root": self.root, "technical": self.technical,
                "headline": self.headline, "details": self.details, "fix": self.fix}


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(dir=folder, prefix=".zeres-write-test-")
        os.close(handle)
        Path(name).unlink(missing_ok=True)
        return True
    except OSError:
        return False


def check(config: Config | None = None) -> DriveStatus:
    """Inspect the configured Drive root and say plainly what is wrong."""
    cfg = config or get_config()
    root = cfg.drive_root
    technical = cfg.technical_root
    status = DriveStatus(root=str(root), technical=str(technical))

    # 1. Still the shipped placeholder — files land inside the app folder.
    if _is_inside(root, PROJECT_ROOT):
        status.level = WARNING
        status.headline = "Documents are being filed inside the app folder, not on Drive."
        status.details = [
            f"The Drive root is still the shipped default: {root}",
            "Everything you upload is being stored there instead of syncing to Drive. "
            "Nothing is lost — the folder structure matches, so it can be moved across later.",
        ]
        status.fix = ("Set [drive] root in config.toml to the folder that CONTAINS your Technical "
                      "folder, using single quotes: root = 'G:\\Shared drives\\...'")
        return status

    # 2. The folder simply is not there.
    if not root.exists():
        status.level = ERROR
        status.headline = "The configured Drive folder does not exist."
        status.details = [
            f"Looked for: {root}",
            "If this is a Google Drive path, check that Google Drive for desktop is running "
            "and the drive letter is mounted.",
        ]
        status.fix = "Correct [drive] root in config.toml, then restart."
        return status

    # 3. The classic mistake: pointing AT the Technical folder rather than at its
    #    parent. The app appends Technical itself, so this silently creates a
    #    second level and nothing lands where anyone is looking.
    looks_like_technical = (
        PurePath(root).name.casefold() == "technical"
        and not technical.exists()
        and any((root / name).exists() for name in EXPECTED)
    )
    if looks_like_technical:
        status.level = ERROR
        status.headline = "The Drive root points at the Technical folder itself, one level too deep."
        status.details = [
            f"Configured: {root}",
            f"The app adds 'Technical' of its own, so it would write into: {technical}",
            f"But {root} already contains " + " and ".join(
                n for n in EXPECTED if (root / n).exists()) + ", so it IS the Technical folder.",
        ]
        status.fix = f"Set [drive] root to the parent instead: '{root.parent}'"
        return status

    # 4. Root is fine but the tree is not there yet.
    if not technical.exists():
        status.level = WARNING
        status.headline = "No Technical folder found under the Drive root yet."
        status.details = [
            f"Expected: {technical}",
            "It will be created the first time a document is filed. If your Drive already has a "
            "Technical folder, the root is probably pointing somewhere else.",
        ]
        status.fix = "Check that [drive] root names the folder that contains Technical."
        return status

    present = [name for name in EXPECTED if (technical / name).exists()]
    if not present:
        status.level = WARNING
        status.headline = "The Technical folder is there, but none of the expected subfolders are."
        status.details = [
            f"Looked in: {technical}",
            f"Expected to find: {', '.join(EXPECTED)}",
            "Subfolders are created on demand, so this is only a problem if you expected an "
            "existing tree here.",
        ]
        status.fix = "Confirm this is the same folder your colleagues see in Drive."
        return status

    if not _writable(technical):
        status.level = ERROR
        status.headline = "The Drive folder is not writable."
        status.details = [
            f"Could not create a file in: {technical}",
            "On a Shared drive this usually means the signed-in Google account has view-only "
            "access. It looks like a normal folder in Explorer but rejects writes.",
        ]
        status.fix = "Ask for edit rights on the Shared drive, or point at a folder you can write to."
        return status

    status.headline = f"Filing to Drive: {technical}"
    status.details = [f"Found {', '.join(present)} — this looks like the right folder."]
    return status


def describe(status: DriveStatus) -> str:
    """The startup banner, for the console."""
    mark = {OK: "OK ", WARNING: "!! ", ERROR: "XX "}[status.level]
    lines = [f"  {mark}{status.headline}"]
    lines += [f"      {d}" for d in status.details]
    if status.fix:
        lines.append(f"      Fix: {status.fix}")
    return "\n".join(lines)
