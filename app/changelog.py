"""The append-only Change Log.

Every field change gets a row: when, who, which record, which field, the old
value, the new value, and why. The 'why' is not decoration — an unexplained MID
status change is exactly what an NEa audit would query, so a status edit without
a source or a note is refused at this layer rather than in the UI.

Nothing in this module ever rewrites or removes an existing entry.
"""

from __future__ import annotations

from typing import Any, Iterable

from . import domain, schema

Row = dict[str, Any]


class ChangeRejected(ValueError):
    """An edit that must not be recorded as-is."""


#: Fields whose change requires a stated reason.
REASON_REQUIRED = frozenset({"MID Status"})


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def diff(before: Row, after: Row, fields: Iterable[str]) -> list[tuple[str, str, str]]:
    """(field, old, new) for every field whose value actually changed."""
    changed = []
    for field in fields:
        old, new = _text(before.get(field)), _text(after.get(field))
        if old != new:
            changed.append((field, old, new))
    return changed


def record(change_log: list[Row], row_id: str, changes: list[tuple[str, str, str]],
           reason: str = "", user: str | None = None) -> list[Row]:
    """Append one entry per changed field. Returns the entries added.

    Raises ChangeRejected if a field in REASON_REQUIRED changed without a reason,
    or if a MID status outside the five-value vocabulary was supplied.
    """
    reason = _text(reason)
    for field, _old, new in changes:
        if field in REASON_REQUIRED:
            if not reason:
                raise ChangeRejected(
                    f"Changing {field} requires a source or a note. An unexplained status "
                    f"change cannot be defended in an NEa audit."
                )
            schema.validate_status(new)   # raises StatusVocabularyError on anything else

    stamp = domain.now_stamp()
    who = user or domain.current_user()
    entries = [
        {"Timestamp": stamp, "User": who, "Row ID": row_id, "Field": field,
         "Old Value": old, "New Value": new,
         "Reason": reason if field in REASON_REQUIRED or reason else ""}
        for field, old, new in changes
    ]
    change_log.extend(entries)
    return entries


def history(change_log: list[Row], row_id: str, limit: int = 50) -> list[Row]:
    """Entries for one record, newest first."""
    matching = [e for e in change_log if _text(e.get("Row ID")) == row_id]
    return list(reversed(matching))[:limit]
