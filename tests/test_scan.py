"""The folder scan — the intake pipeline over a local folder, minus the uploading."""

import shutil
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_pdf import make_pdf  # noqa: E402

from app import config as config_module  # noqa: E402
from app.intake import scan  # noqa: E402

DOC_LINES = ["EU DECLARATION OF CONFORMITY - Alfen N.V.",
             "Models: Eve Single Pro-line",
             "In conformity with Directive 2014/32/EU (MID), MI-003.",
             "Certificate T10402 issued by NMi Certin B.V."]


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "Docs"
    (root / "Alfen").mkdir(parents=True)
    (root / "Overig").mkdir()
    make_pdf(root / "Alfen" / "Alfen_Eve_DoC.pdf", DOC_LINES)
    make_pdf(root / "Overig" / "scan0034.pdf", ["CE marked. 22 kW."])
    (root / "Overig" / "tracker.xlsx").write_bytes(b"ignored")
    (root / "Overig" / "~$temp.pdf").write_bytes(b"office lockfile")
    (root / "Overig" / "empty.pdf").write_bytes(b"")
    return root


# ── discovery ──────────────────────────────────────────────────────────────

def test_discovery_reads_documents_and_counts_the_rest(folder):
    files, ignored, truncated = scan.discover(folder)
    assert [f.name for f in files] == ["Alfen_Eve_DoC.pdf", "scan0034.pdf"]
    assert ignored == 2                    # the .xlsx and the 0-byte pdf
    assert not truncated                   # lockfiles are not even counted


def test_discovery_caps_a_huge_folder_rather_than_choking(tmp_path, monkeypatch):
    monkeypatch.setattr(scan, "MAX_FILES", 3)
    for i in range(5):
        (tmp_path / f"d{i}.pdf").write_bytes(b"%PDF-1.4 x")
    files, _, truncated = scan.discover(tmp_path)
    assert len(files) == 3 and truncated


def test_an_installer_sized_file_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(scan, "MAX_FILE_BYTES", 10)
    (tmp_path / "video.pdf").write_bytes(b"x" * 50)
    files, ignored, _ = scan.discover(tmp_path)
    assert files == [] and ignored == 1


# ── guessing ───────────────────────────────────────────────────────────────

def test_kind_comes_from_the_filename_then_the_folder_default():
    assert scan.guess_kind(Path("Alfen_conformity.pdf")) == "doc"
    assert scan.guess_kind(Path("handleiding_installatie.pdf")) == "manual"
    assert scan.guess_kind(Path("nameplate.jpg")) == "photo"
    assert scan.guess_kind(Path("scan0034.pdf"), default="doc") == "doc"
    assert scan.guess_kind(Path("scan0034.pdf")) == "datasheet"


def test_brand_prefers_the_folder_over_the_filename(tmp_path):
    path = tmp_path / "Wallbox" / "Alfen_DoC.pdf"
    assert scan.guess_brand(path, ["Alfen", "Wallbox"], tmp_path) == "Wallbox"


def test_brand_falls_back_to_the_filename(tmp_path):
    path = tmp_path / "Overig" / "BlueCurrent_DoC.pdf"
    assert scan.guess_brand(path, ["Alfen", "Blue Current"], tmp_path) == "Blue Current"


def test_a_short_brand_never_matches_by_accident(tmp_path):
    """'Go' or 'S' as a brand token would match half the filenames on disk."""
    path = tmp_path / "gonzo_specs.pdf"
    assert scan.guess_brand(path, ["Go"], tmp_path) == ""


# ── the scan itself, through the API ───────────────────────────────────────

@pytest.fixture
def client(sandbox, tmp_path):
    from app import server
    config_module.override_config(drive_root=tmp_path / "Drive")
    server.reload_register()
    server._intake.clear()
    server._scan = None
    with TestClient(server.app) as c:
        yield c


def _wait(client):
    for _ in range(80):
        status = client.get("/api/intake/scan/status").json()
        if not status.get("running", True):
            return status
        time.sleep(0.1)
    raise AssertionError("scan never finished")


def test_a_scan_stages_proposals_without_applying_anything(client, folder):
    from app import server, storage
    before = len(storage.load().change_log)
    response = client.post("/api/intake/scan", json={"folder": str(folder), "defaultKind": "doc"})
    assert response.status_code == 200
    status = _wait(client)

    assert status["staged"] == 2 and status["failures"] == []
    items = {i["filename"]: i for i in client.get("/api/intake").json()["items"]}
    alfen = items["Alfen_Eve_DoC.pdf"]
    assert alfen["brand"] == "Alfen"                       # from the folder
    assert alfen["proposal"]["status"] == "Integrated"
    assert alfen["proposal"]["doc"]["certificate_number"] == "T10402"
    assert items["scan0034.pdf"]["proposal"]["status"] == "Unknown"   # CE only
    assert len(storage.load().change_log) == before        # nothing applied


def test_a_rescan_skips_what_the_conformity_register_already_holds(client, folder):
    client.post("/api/intake/scan", json={"folder": str(folder), "defaultKind": "doc"})
    _wait(client)
    items = client.get("/api/intake").json()["items"]
    alfen = next(i for i in items if i["filename"] == "Alfen_Eve_DoC.pdf")

    # A human applies the declaration...
    client.post("/api/conformity", json={"brand": "Alfen", "doc": alfen["proposal"]["doc"],
                                         "stored": alfen["stored"], "applyTo": []})
    for item in items:
        client.delete(f"/api/intake/{item['id']}")        # fresh session

    client.post("/api/intake/scan", json={"folder": str(folder), "defaultKind": "doc"})
    status = _wait(client)
    assert status["skippedApplied"] == 1                  # the done work stays done
    assert status["staged"] == 1                          # the CE-only one resurfaces


def test_a_scan_does_not_stage_the_same_bytes_twice(client, folder):
    shutil.copy(folder / "Alfen" / "Alfen_Eve_DoC.pdf", folder / "Alfen" / "kopie.pdf")
    client.post("/api/intake/scan", json={"folder": str(folder), "defaultKind": "doc"})
    status = _wait(client)
    assert status["skippedStaged"] == 1


def test_an_unreadable_file_is_reported_not_fatal(client, folder):
    (folder / "Overig" / "broken.pdf").write_bytes(b"pdf in name only")
    client.post("/api/intake/scan", json={"folder": str(folder), "defaultKind": "doc"})
    status = _wait(client)
    assert status["done"] == status["total"] == 3
    # pdfplumber treats it as unreadable -> staged with a warning, or a failure;
    # either way the other two documents made it through.
    assert status["staged"] >= 2


def test_a_web_url_is_refused_with_directions(client):
    response = client.post("/api/intake/scan",
                           json={"folder": "https://drive.google.com/drive/folders/abc"})
    assert response.status_code == 422
    assert "local synced path" in response.json()["detail"]


def test_a_missing_folder_is_refused(client):
    assert client.post("/api/intake/scan", json={"folder": "Q:\\does\\not\\exist"}).status_code == 422
    assert client.post("/api/intake/scan", json={"folder": ""}).status_code == 422
