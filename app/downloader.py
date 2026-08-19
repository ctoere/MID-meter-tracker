"""Fetches queued datasheets into the Drive tree. Replaces sync_datasheets.ps1.

Why we keep our own copy at all: a datasheet is the evidence behind a compliance
claim, and the manufacturer can revise or delete it from their site at any time.
The file we captured is the one that matters in an audit, not the URL.

Behaviour:
  - idempotent: a file that already exists and is non-empty is skipped
  - concurrent, capped by config so we don't hammer a manufacturer's CDN
  - retries with exponential backoff on transport errors and 5xx/429
  - sends a real browser User-Agent (several vendor CDNs 403 anything else)
  - a manifest row with no Url is skipped silently — those datasheets came
    straight from the manufacturer and are filed by hand, they are not failures
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import httpx

from .config import get_config

Row = dict[str, Any]

#: Worth retrying: transient server-side or rate-limit responses.
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass
class FileResult:
    brand: str
    model: str
    filename: str
    path: str
    status: str          # downloaded | skipped | no-url | failed
    detail: str = ""
    bytes: int = 0

    @property
    def ok(self) -> bool:
        return self.status in {"downloaded", "skipped", "no-url"}


@dataclass
class Job:
    """A running or finished download run, polled by the UI."""
    total: int = 0
    done: int = 0
    running: bool = True
    results: list[FileResult] = field(default_factory=list)

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return {
            "total": self.total, "done": self.done, "running": self.running,
            "counts": counts,
            "results": [r.__dict__ for r in self.results],
        }


def target_path(row: Row, root: Path | None = None) -> Path:
    """<DriveRoot>/Technical/<SubFolder>/<Filename>, backslashes translated."""
    cfg = get_config()
    base = root or cfg.technical_root
    subfolder = str(row.get("SubFolder", "") or "").replace("\\", "/").strip("/")
    filename = str(row.get("Filename", "") or "").strip()
    return base.joinpath(*subfolder.split("/"), filename) if subfolder else base / filename


def already_have(path: Path) -> bool:
    """Idempotency test: present and non-empty. A 0-byte file is a failed fetch."""
    return path.exists() and path.stat().st_size > 0


async def _fetch_one(client: httpx.AsyncClient, row: Row, root: Path | None,
                     semaphore: asyncio.Semaphore, job: Job, max_retries: int) -> FileResult:
    brand = str(row.get("Brand", "") or "")
    model = str(row.get("Model", "") or "")
    filename = str(row.get("Filename", "") or "")
    url = str(row.get("Url", "") or "").strip()
    path = target_path(row, root)

    def finish(result: FileResult) -> FileResult:
        job.results.append(result)
        job.done += 1
        return result

    if not url:
        # Filed by hand — legitimate, not a failure.
        return finish(FileResult(brand, model, filename, str(path), "no-url",
                                 "no public link; filed by hand"))
    if already_have(path):
        return finish(FileResult(brand, model, filename, str(path), "skipped",
                                 "already on disk", path.stat().st_size))

    delay = 1.0
    last = ""
    async with semaphore:
        for attempt in range(1, max_retries + 1):
            try:
                response = await client.get(url, follow_redirects=True)
                if response.status_code in RETRY_STATUS:
                    last = f"HTTP {response.status_code}"
                    if attempt < max_retries:
                        await asyncio.sleep(delay)
                        delay *= 2
                        continue
                elif response.status_code >= 400:
                    return finish(FileResult(brand, model, filename, str(path), "failed",
                                             f"HTTP {response.status_code}"))
                else:
                    body = response.content
                    if not body:
                        return finish(FileResult(brand, model, filename, str(path), "failed",
                                                 "empty response"))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    # Write via a temp file so an interrupted fetch never leaves a
                    # half-file that the next run would treat as already downloaded.
                    temp = path.with_suffix(path.suffix + ".part")
                    temp.write_bytes(body)
                    temp.replace(path)
                    return finish(FileResult(brand, model, filename, str(path),
                                             "downloaded", "", len(body)))
            except (httpx.TransportError, httpx.HTTPError) as exc:
                last = f"{type(exc).__name__}: {exc}"
                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2

    return finish(FileResult(brand, model, filename, str(path), "failed",
                             last or "gave up after retries"))


async def run(rows: Iterable[Row], job: Job, root: Path | None = None) -> Job:
    cfg = get_config()
    rows = list(rows)
    job.total = len(rows)
    semaphore = asyncio.Semaphore(cfg.max_concurrent)
    headers = {"User-Agent": cfg.user_agent, "Accept": "*/*"}
    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds, headers=headers) as client:
            await asyncio.gather(*(
                _fetch_one(client, row, root, semaphore, job, cfg.max_retries) for row in rows
            ))
    finally:
        job.running = False
    return job
