"""Scanning a local folder full of documents into the intake pipeline.

The conformity backlog arrives as folders — "here are 150 declarations we
collected" — and dragging them into a browser one batch at a time is friction
with no compliance value. The scan walks a folder the user names (typically a
Drive-synced path, so the files are already local), runs every document through
the same store → extract → propose pipeline as a drag-and-drop, and leaves the
person with what actually needs their judgement: a queue of proposals to
approve or skip.

Nothing here applies anything. The scan produces the same staged intake items an
upload does, with the same human apply step; it only removes the uploading.

Skipping rules, because a folder will be scanned more than once:
  - a file whose SHA-256 is already recorded in the Conformity sheet was
    processed and applied — skipped, that work is done
  - a file whose hash is already staged in this session is not staged twice
  - a file whose bytes already sit in the Drive tree but were never applied is
    staged again, marked as a duplicate, so unfinished work resurfaces
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import domain
from .extract import IMAGE_SUFFIXES, PDF_SUFFIXES

#: What a scan will pick up. Anything else in the folder is ignored, counted,
#: and reported — never an error: real folders contain .xlsx trackers, .url
#: shortcuts and desktop.ini, and a scan that trips over them is useless.
ALLOWED_SUFFIXES = PDF_SUFFIXES | IMAGE_SUFFIXES

#: A conformity statement is a few hundred KB. Anything this size is a video or
#: an installer that wandered in, and reading it would only stall the scan.
MAX_FILE_BYTES = 50 * 1024 * 1024

#: One scan processes at most this many files. A cap, not pagination: if a
#: folder holds more, the report says so and the user scans a subfolder.
MAX_FILES = 300

_DOC_HINTS = re.compile(r"conform|declar|verklaring|konformit|certifi|ce[-_ ]?doc|\bdoc\b|EU[-_ ]?DoC",
                        re.IGNORECASE)
_MANUAL_HINTS = re.compile(r"manual|install|handleiding|anleitung", re.IGNORECASE)
_DATASHEET_HINTS = re.compile(r"datasheet|productsheet|spec|brochure|leaflet", re.IGNORECASE)


@dataclass
class ScanJob:
    """Progress of one folder scan, polled by the UI."""
    folder: str = ""
    running: bool = True
    total: int = 0
    done: int = 0
    staged: int = 0
    skipped_applied: int = 0     # hash already in the Conformity sheet
    skipped_staged: int = 0      # hash already staged this session
    duplicates: int = 0          # bytes already in the Drive tree, staged anyway
    ignored: int = 0             # extension the scan does not read
    failures: list[dict] = field(default_factory=list)
    truncated: bool = False

    def summary(self) -> dict:
        return {
            "folder": self.folder, "running": self.running,
            "total": self.total, "done": self.done, "staged": self.staged,
            "skippedApplied": self.skipped_applied, "skippedStaged": self.skipped_staged,
            "duplicates": self.duplicates, "ignored": self.ignored,
            "failures": self.failures, "truncated": self.truncated,
        }


def discover(folder: Path) -> tuple[list[Path], int, bool]:
    """(files to process, ignored count, truncated?) — deterministic order."""
    candidates: list[Path] = []
    ignored = 0
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name.startswith((".", "~$")):
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            ignored += 1
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES or path.stat().st_size == 0:
                ignored += 1
                continue
        except OSError:
            ignored += 1
            continue
        candidates.append(path)

    truncated = len(candidates) > MAX_FILES
    return candidates[:MAX_FILES], ignored, truncated


def guess_kind(path: Path, default: str = "") -> str:
    """Kind from the filename, with the caller's default winning over 'datasheet'.

    A scan of a conformity folder passes default='doc', so an unhelpfully named
    file still lands as the thing the folder is full of.
    """
    name = path.name
    if path.suffix.lower() in IMAGE_SUFFIXES:
        return "photo"
    if _DOC_HINTS.search(name):
        return "doc"
    if _MANUAL_HINTS.search(name):
        return "manual"
    if _DATASHEET_HINTS.search(name):
        return "datasheet"
    return default or "datasheet"


def guess_brand(path: Path, known_brands: list[str], root: Path) -> str:
    """Match the file's name and its folders against brands the register knows.

    The folder name outranks the filename — a tree organised as <Brand>/<files>
    is the convention, and a file called 'Alfen_DoC.pdf' inside 'Wallbox/' is
    more likely misfiled than misnamed... but that judgement belongs to the
    human, so the folder wins and the proposal is theirs to correct.

    Longest normalised match wins, so 'Blue Current' beats 'Blue'.
    """
    normalise = lambda s: re.sub(r"[^0-9a-z]+", "", s.lower())
    ranked = sorted(((normalise(b), b) for b in known_brands if len(normalise(b)) >= 3),
                    key=lambda t: -len(t[0]))

    try:
        parts = list(path.relative_to(root).parts[:-1])   # folders only
    except ValueError:
        parts = []
    for haystack in [*(normalise(p) for p in reversed(parts)), normalise(path.stem)]:
        for norm, brand in ranked:
            if norm and norm in haystack:
                return brand
    return ""


def applied_hashes(conformity_rows: list[dict]) -> set[str]:
    """SHA-256es of documents already recorded in the Conformity sheet."""
    return {str(row.get("SHA-256", "") or "").strip()
            for row in conformity_rows} - {""}
