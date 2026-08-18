"""Phase 4 — the downloader, against a real local HTTP server rather than mocks.

Exercising real HTTP keeps the retry, redirect and status handling honest.
"""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import config as config_module
from app import downloader

STATE = {"flaky_hits": 0}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/good.pdf":
            body = b"%PDF-1.4 fake datasheet"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/missing.pdf":
            self.send_response(404); self.end_headers()
        elif self.path == "/empty.pdf":
            self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers()
        elif self.path == "/flaky.pdf":
            STATE["flaky_hits"] += 1
            if STATE["flaky_hits"] == 1:            # fail once, then succeed
                self.send_response(503); self.end_headers()
            else:
                body = b"%PDF-1.4 recovered"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        elif self.path == "/ua":
            body = self.headers.get("User-Agent", "").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(500); self.end_headers()


@pytest.fixture
def http_server():
    STATE["flaky_hits"] = 0
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def drive(tmp_path):
    root = tmp_path / "Drive"
    config_module.override_config(drive_root=root, max_retries=2, timeout_seconds=5,
                                 max_concurrent=4)
    yield root / "Technical"
    config_module.reset_config()


def row(url, filename, sub="Chargers\\AC Chargers\\Alfen", brand="Alfen", model="Eve"):
    return {"Brand": brand, "Model": model, "SubFolder": sub, "Url": url, "Filename": filename}


def run(rows, drive):
    job = downloader.Job()
    asyncio.run(downloader.run(rows, job, root=drive))
    return job


def by_file(job):
    return {r.filename: r for r in job.results}


def test_downloads_into_the_drive_tree(http_server, drive):
    job = run([row(f"{http_server}/good.pdf", "Alfen_Eve_datasheet.pdf")], drive)
    result = by_file(job)["Alfen_Eve_datasheet.pdf"]
    assert result.status == "downloaded"
    target = drive / "Chargers" / "AC Chargers" / "Alfen" / "Alfen_Eve_datasheet.pdf"
    assert target.read_bytes() == b"%PDF-1.4 fake datasheet"


def test_backslash_subfolders_become_real_directories(http_server, drive):
    run([row(f"{http_server}/good.pdf", "x.pdf", sub="Meters\\Inepro", brand="Inepro")], drive)
    assert (drive / "Meters" / "Inepro" / "x.pdf").exists()


def test_is_idempotent(http_server, drive):
    rows = [row(f"{http_server}/good.pdf", "a.pdf")]
    assert by_file(run(rows, drive))["a.pdf"].status == "downloaded"
    assert by_file(run(rows, drive))["a.pdf"].status == "skipped"


def test_a_zero_byte_file_is_not_treated_as_downloaded(http_server, drive):
    """A previous failed run must not make the next one skip the file."""
    target = drive / "Chargers" / "AC Chargers" / "Alfen" / "a.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"")
    assert by_file(run([row(f"{http_server}/good.pdf", "a.pdf")], drive))["a.pdf"].status == "downloaded"
    assert target.stat().st_size > 0


def test_empty_url_rows_are_skipped_silently_not_failed(http_server, drive):
    """Some datasheets came from the manufacturer directly and are filed by hand."""
    result = by_file(run([row("", "hand_filed.pdf")], drive))["hand_filed.pdf"]
    assert result.status == "no-url"
    assert result.ok                       # not counted as a failure


def test_a_404_is_reported_as_failed(http_server, drive):
    result = by_file(run([row(f"{http_server}/missing.pdf", "gone.pdf")], drive))["gone.pdf"]
    assert result.status == "failed"
    assert "404" in result.detail
    assert not (drive / "Chargers" / "AC Chargers" / "Alfen" / "gone.pdf").exists()


def test_an_empty_body_is_a_failure_not_an_empty_file(http_server, drive):
    result = by_file(run([row(f"{http_server}/empty.pdf", "e.pdf")], drive))["e.pdf"]
    assert result.status == "failed"
    assert not (drive / "Chargers" / "AC Chargers" / "Alfen" / "e.pdf").exists()


def test_retries_a_transient_failure(http_server, drive):
    result = by_file(run([row(f"{http_server}/flaky.pdf", "f.pdf")], drive))["f.pdf"]
    assert result.status == "downloaded"
    assert STATE["flaky_hits"] == 2         # failed once, retried, succeeded


def test_sends_a_real_user_agent(http_server, drive):
    run([row(f"{http_server}/ua", "ua.txt")], drive)
    sent = (drive / "Chargers" / "AC Chargers" / "Alfen" / "ua.txt").read_text()
    assert "Mozilla/5.0" in sent            # several vendor CDNs 403 anything else


def test_one_failure_does_not_stop_the_others(http_server, drive):
    job = run([row(f"{http_server}/missing.pdf", "bad.pdf"),
               row(f"{http_server}/good.pdf", "good.pdf"),
               row("", "hand.pdf")], drive)
    results = by_file(job)
    assert results["bad.pdf"].status == "failed"
    assert results["good.pdf"].status == "downloaded"
    assert results["hand.pdf"].status == "no-url"
    assert job.done == 3 and not job.running


def test_summary_counts_each_outcome(http_server, drive):
    job = run([row(f"{http_server}/good.pdf", "a.pdf"),
               row(f"{http_server}/missing.pdf", "b.pdf")], drive)
    counts = job.summary()["counts"]
    assert counts["downloaded"] == 1 and counts["failed"] == 1


def test_no_part_files_are_left_behind(http_server, drive):
    run([row(f"{http_server}/good.pdf", "a.pdf")], drive)
    assert list(drive.rglob("*.part")) == []
