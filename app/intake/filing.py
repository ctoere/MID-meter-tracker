"""Storing intake documents in the Drive tree.

A datasheet is the evidence behind a compliance claim, and the manufacturer can
revise or delete it from their site at any time — so the copy we captured is the
one that matters. Two rules follow:

  - keep the original bytes, unmodified
  - never overwrite. A file arriving under a name we already hold is stored as
    _v2, _v3 and so on, because the older revision is what an earlier claim was
    based on and deleting it destroys the audit trail.

Every stored file's SHA-256 is recorded, so an identical re-upload is recognised
and a quietly revised document is detectable.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import domain
from ..config import get_config
from .extract import sha256

#: Where each kind of document lives, below <DriveRoot>/Technical.
KIND_FOLDERS = {
    "datasheet": "Chargers/{ac_dc} Chargers/{brand}",
    "manual": "Chargers/{ac_dc} Chargers/{brand}",
    "meter": "Meters/{brand}",
    "photo": "Evidence/Photos/{brand}",
    "doc": "Evidence/Conformity/{brand}",
    "other": "Evidence/Other/{brand}",
}


@dataclass
class StoredFile:
    path: str
    relative: str
    sha256: str
    bytes: int
    duplicate_of: str = ""      # set when the identical bytes were already stored


def _safe(part: str) -> str:
    """A folder-safe brand name that still matches the Drive tree's spelling."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(part or "").strip())
    return cleaned or "Unsorted"


def target_folder(kind: str, brand: str, charge_type: str = "AC", root: Path | None = None) -> Path:
    template = KIND_FOLDERS.get(kind, KIND_FOLDERS["other"])
    relative = template.format(ac_dc=domain.charge_type_folder(charge_type), brand=_safe(brand))
    base = root or get_config().technical_root
    return base.joinpath(*relative.split("/"))


def _next_free(folder: Path, filename: str) -> Path:
    """`x.pdf` -> `x_v2.pdf` -> `x_v3.pdf`. Never returns an existing path."""
    candidate = folder / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    version = 2
    while True:
        candidate = folder / f"{stem}_v{version}{suffix}"
        if not candidate.exists():
            return candidate
        version += 1


def store(source: Path, kind: str, brand: str, filename: str | None = None,
          charge_type: str = "AC", root: Path | None = None) -> StoredFile:
    """Copy ``source`` into the Drive tree without ever replacing a file."""
    source = Path(source)
    folder = target_folder(kind, brand, charge_type, root)
    folder.mkdir(parents=True, exist_ok=True)

    digest = sha256(source)

    # An identical file already filed here is not stored twice — but it is
    # reported, so the user knows this document was already captured.
    for existing in folder.iterdir():
        if existing.is_file() and existing.stat().st_size == source.stat().st_size:
            if sha256(existing) == digest:
                base = root or get_config().technical_root
                return StoredFile(str(existing), str(existing.relative_to(base.parent)),
                                  digest, existing.stat().st_size, duplicate_of=existing.name)

    target = _next_free(folder, filename or source.name)
    shutil.copy2(source, target)
    base = root or get_config().technical_root
    return StoredFile(str(target), str(target.relative_to(base.parent)),
                      digest, target.stat().st_size)


def suggested_filename(brand: str, model: str, kind: str, suffix: str) -> str:
    """<Brand>_<ModelNoSpaces>_<kind>.<ext>, matching the manifest convention."""
    tag = {"datasheet": "datasheet", "doc": "conformity", "photo": "nameplate",
           "manual": "manual", "meter": "datasheet"}.get(kind, "document")
    return f"{domain.brand_slug(brand) or 'Unknown'}_{domain.model_slug(model)}_{tag}{suffix}"


def refile(stored: StoredFile, kind: str, brand: str, model: str,
           charge_type: str = "AC", root: Path | None = None) -> StoredFile:
    """Move an already-stored file once a human corrects its brand/kind tagging.

    Files are stored the moment they arrive, before anyone has said what they
    are — losing the bytes would be worse than filing them imprecisely. So the
    first landing is often Unsorted. When the tagging is corrected, the captured
    copy moves to where it belongs rather than being left behind or copied twice.

    This moves rather than re-copies, so there is still exactly one stored copy
    and its SHA-256 is unchanged.
    """
    current = Path(stored.path)
    if not current.exists():
        return stored

    folder = target_folder(kind, brand, charge_type, root)
    desired = folder / suggested_filename(brand, model, kind, current.suffix)
    if desired == current:
        return stored

    folder.mkdir(parents=True, exist_ok=True)
    target = _next_free(folder, desired.name)
    current.replace(target)

    # Leave no empty directory behind from the provisional filing.
    try:
        next(current.parent.iterdir())
    except StopIteration:
        current.parent.rmdir()
    except OSError:
        pass

    base = root or get_config().technical_root
    return StoredFile(str(target), str(target.relative_to(base.parent)),
                      stored.sha256, target.stat().st_size)
