"""Gap detection — the register looking complete while the queue has holes."""

from app import manifest, storage

KNOWN_GAPS = {
    "https://www.alfenelkamo.fi/sites/elkamo.fi/files/downloads/Manual-Eve-Mini_0.pdf",
    "https://www.go-e.sk/wp-content/uploads/2019/09/kecontactp30technicaldata_dben.pdf",
    "https://volttime.com/wp-content/uploads/2023/05/Volt-Time-Source-2-Brochure-EN.pdf",
}


def test_finds_the_known_gaps(sandbox):
    register = storage.load()
    gaps = manifest.find_gaps(register.chargers, register.meters, register.manifest)
    assert {g["Datasheet Link"] for g in gaps} == KNOWN_GAPS


def test_catches_a_row_removed_from_the_queue(sandbox):
    register = storage.load()
    baseline = len(manifest.find_gaps(register.chargers, register.meters, register.manifest))

    linked = next(c for c in register.chargers
                  if c["Datasheet Link"] in manifest.queued_urls(register.manifest))
    register.manifest = [m for m in register.manifest if m["Url"] != linked["Datasheet Link"]]

    gaps = manifest.find_gaps(register.chargers, register.meters, register.manifest)
    assert len(gaps) == baseline + 1
    assert linked["Datasheet Link"] in {g["Datasheet Link"] for g in gaps}


def test_gap_count_is_unchanged_by_a_no_op_save(sandbox):
    register = storage.load()
    before = len(manifest.find_gaps(register.chargers, register.meters, register.manifest))
    storage.save(register)
    reloaded = storage.load()
    after = len(manifest.find_gaps(reloaded.chargers, reloaded.meters, reloaded.manifest))
    assert after == before == 3


def test_blank_url_rows_are_not_failures(sandbox):
    """Some datasheets came from the manufacturer directly and are filed by hand."""
    register = storage.load()
    register.manifest.append({"Brand": "Alfen", "Model": "Hand filed",
                              "SubFolder": "Chargers\\AC Chargers\\Alfen", "Url": "", "Filename": "x.pdf"})
    assert "" not in manifest.queued_urls(register.manifest)
    # and it does not create a gap for itself
    assert len(manifest.find_gaps(register.chargers, register.meters, register.manifest)) == 3


def test_queueing_gaps_closes_them(sandbox):
    register = storage.load()
    gaps = manifest.find_gaps(register.chargers, register.meters, register.manifest)
    added = manifest.queue_rows(register.manifest, gaps)
    assert len(added) == 3
    assert manifest.find_gaps(register.chargers, register.meters, register.manifest) == []


def test_queueing_is_idempotent(sandbox):
    register = storage.load()
    gaps = manifest.find_gaps(register.chargers, register.meters, register.manifest)
    manifest.queue_rows(register.manifest, gaps)
    assert manifest.queue_rows(register.manifest, gaps) == []


def test_manifest_row_follows_the_drive_conventions():
    row = {"Brand": "Alfen", "Model": "Eve Single Plus", "Charge Type": "AC",
           "Datasheet Link": "https://example.com/x.pdf"}
    entry = manifest.manifest_row_for(row)
    assert entry["SubFolder"] == "Chargers\\AC Chargers\\Alfen"
    assert entry["Filename"] == "Alfen_EveSinglePlus_datasheet.pdf"

    dc = manifest.manifest_row_for({**row, "Brand": "ABB", "Charge Type": "DC",
                                    "Model": "Terra DC Wallbox"})
    assert dc["SubFolder"] == "Chargers\\DC Chargers\\ABB"

    meter = manifest.manifest_row_for({"Brand": "Inepro", "Model": "PRO380",
                                       "Datasheet Link": "https://example.com/y.pdf"}, is_meter=True)
    assert meter["SubFolder"] == "Meters\\Inepro"


def test_html_datasheets_keep_their_extension():
    """A couple of manufacturers publish no PDF at all."""
    entry = manifest.manifest_row_for({"Brand": "Tesla", "Model": "Wall Connector Gen 3 MID",
                                       "Charge Type": "AC",
                                       "Datasheet Link": "https://example.com/spec.html"})
    assert entry["Filename"].endswith(".html")
