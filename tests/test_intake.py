"""Phase 5 — intake. Mostly a test of what the tool refuses to conclude."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_pdf import CE_ONLY, FULL_MARKINGS, make_pdf  # noqa: E402

from app import config as config_module  # noqa: E402
from app.intake import extract, filing, markings, proposals  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ── the marking detector ───────────────────────────────────────────────────

def test_finds_the_full_set_of_markings():
    found = markings.detect("CE M 26 0122 MI-003 Class B EN 50470-3")
    kinds = {m.kind for m in found.mid_evidence}
    assert {"metrology_m", "notified_body", "mi_003", "en_50470", "accuracy_class"} <= kinds
    assert found.has_mid_evidence


def test_finds_nothing_metrological_in_a_ce_only_string():
    """The single most common false positive on this job."""
    found = markings.detect("The product is CE marked and complies with the EMC Directive.")
    assert found.mid_evidence == []
    assert found.ce_only
    assert [m.kind for m in found.markings] == ["ce"]


def test_ce_is_recorded_as_seen_but_never_as_evidence():
    found = markings.detect("CE M 26 0122 MI-003")
    ce = found.of_kind("ce")
    assert ce and not any(m.is_mid_evidence for m in ce)


def test_the_m_marking_year_is_read_out():
    found = markings.detect("meter bears M 26 0122")
    assert "2026" in found.of_kind("metrology_m")[0].detail


def test_a_bolt_size_is_not_a_metrology_marking():
    assert markings.detect("Mounting hardware: M 8 bolts, torque 20 Nm.").of_kind("metrology_m") == []


def test_iec_62053_class_1_is_not_mid_evidence():
    """Class 1/2 under IEC 62053 is the older, non-MID scheme."""
    found = markings.detect("Internal metering to IEC 62053-21, class 1 accuracy.")
    assert not found.has_mid_evidence
    assert found.of_kind("iec_62053")
    assert all(not m.is_mid_evidence for m in found.of_kind("iec_class"))


def test_accuracy_class_only_counts_when_en_50470_is_cited():
    with_standard = markings.detect("Class B to EN 50470-3")
    without = markings.detect("Class B accuracy")
    assert with_standard.of_kind("accuracy_class")[0].is_mid_evidence
    assert not without.of_kind("accuracy_class")[0].is_mid_evidence


def test_eichrecht_is_recorded_but_not_counted():
    found = markings.detect("Das Gerat ist eichrechtskonform nach PTB-A 50.7.")
    assert found.of_kind("eichrecht")
    assert not found.has_mid_evidence
    assert found.eichrecht_only


def test_markings_carry_the_sentence_they_were_found_in():
    text = ("The enclosure is IP54 rated. The integrated meter carries MI-003 and "
            "Class B to EN 50470-3. Cable length is 5 m.")
    sentence = markings.detect(text).of_kind("mi_003")[0].sentence
    assert "MI-003" in sentence and "IP54" not in sentence and "Cable" not in sentence


# ── proposals ──────────────────────────────────────────────────────────────

def test_full_markings_propose_integrated():
    p = proposals.decide("CE M 26 0122 MI-003 Class B EN 50470-3", "datasheet")
    assert p.status == "Integrated"


def test_ce_only_proposes_unknown_never_none():
    p = proposals.decide("The product is CE marked and complies with the EMC Directive.", "datasheet")
    assert p.status == "Unknown"
    assert p.status != "None"
    assert "not metrology" in " ".join(p.reasoning)


def test_optional_wording_proposes_optional_not_integrated():
    p = proposals.decide("MI-003 certified meter available as an option on the M variant.", "datasheet")
    assert p.status == "Optional"


def test_external_wording_proposes_external():
    p = proposals.decide("No built-in meter; an external MID meter (MI-003) can be fitted.", "datasheet")
    assert p.status == "External"


def test_a_positive_denial_may_propose_none():
    p = proposals.decide("This model has no MID meter and no metering option is offered.", "datasheet")
    assert p.status == "None"


def test_silence_proposes_unknown():
    p = proposals.decide("Rated 22 kW, Type 2 socket, IP54.", "datasheet")
    assert p.status == "Unknown"


# ── the nameplate rule ─────────────────────────────────────────────────────

def test_an_exterior_photo_can_never_prove_absence():
    """On most wallboxes the meter sits behind the cover."""
    p = proposals.decide("ALFEN EVE SINGLE  Art. 904460  230V 32A  CE",
                         "photo", proposals.SURFACE_EXTERIOR)
    assert p.status == "Unknown"
    assert "behind the cover" in " ".join(p.reasoning)


def test_an_exterior_photo_with_no_markings_at_all_is_still_unknown():
    p = proposals.decide("SOME BRAND  230V  32A", "photo", proposals.SURFACE_EXTERIOR)
    assert p.status == "Unknown"


def test_an_untagged_photo_concludes_nothing():
    p = proposals.decide("M 26 0122 MI-003", "photo", proposals.SURFACE_UNKNOWN)
    assert p.status == "Unknown"
    assert "what surface" in " ".join(p.reasoning)


def test_a_photo_of_the_meter_itself_can_establish_mid():
    p = proposals.decide("M 26 0122 MI-003 Class B EN 50470-3", "photo", proposals.SURFACE_METER)
    assert p.status == "Integrated"


# ── declarations of conformity ─────────────────────────────────────────────

def test_a_doc_without_the_directive_is_not_mid_evidence():
    text = ("EU Declaration of Conformity. Certificate: ABC-1234. The EVSE complies with "
            "Directive 2014/35/EU (LVD) and 2014/30/EU (EMC).")
    p = proposals.decide(text, "doc")
    assert p.status == "Unknown"
    assert p.doc is not None and not p.doc.directive_cited
    assert "does not cite" in " ".join(p.reasoning)


def test_a_doc_citing_the_directive_is_read_out():
    text = ("EU Declaration of Conformity. Certificate: T10402 issued by NMi. "
            "In accordance with Directive 2014/32/EU, MI-003. Models: PRO380-Mod, PRO380-S.")
    p = proposals.decide(text, "doc")
    assert p.doc.directive_cited
    assert p.doc.certificate_number == "T10402"
    assert p.doc.issuing_body == "NMi"
    assert any("PRO380" in m for m in p.doc.models_covered)
    assert p.status == "Integrated"


# ── the diff, and applying nothing ─────────────────────────────────────────

def test_the_proposal_diffs_against_the_current_row():
    current = {"Brand": "ABB", "Model": "Terra AC Wallbox", "MID Status": "External"}
    p = proposals.build("MI-003 Class B EN 50470-3", "datasheet", "ABB", "Terra AC Wallbox", current)
    status_row = next(d for d in p.diff if d["field"] == "MID Status")
    assert status_row["current"] == "External" and status_row["proposed"] == "Integrated"
    assert any(d["field"].startswith("⚠") for d in p.diff)


def test_a_matching_proposal_shows_no_change():
    current = {"Brand": "ABB", "Model": "X", "MID Status": "Integrated"}
    p = proposals.build("MI-003 EN 50470-3 Class B", "datasheet", "ABB", "X", current)
    assert not any(d["changed"] for d in p.diff)


# ── extraction ─────────────────────────────────────────────────────────────

def test_reads_text_out_of_a_real_pdf(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf", FULL_MARKINGS)
    result = extract.extract(pdf)
    assert result.method == "pdf-text" and result.pages == 1
    assert "MI-003" in result.text


def test_acceptance_full_pdf_proposes_integrated_with_every_marking_and_a_quote():
    result = extract.extract(FIXTURES / "acceptance_full.pdf")
    p = proposals.decide(result.text, "datasheet")
    assert p.status == "Integrated"
    kinds = {m["kind"] for m in p.matched}
    assert {"metrology_m", "notified_body", "mi_003", "accuracy_class"} <= kinds
    assert any("M 26 0122" in q and "MI-003" in q for q in p.quotes)
    assert any(m["kind"] == "ce" for m in p.discounted)


def test_acceptance_ce_only_pdf_proposes_unknown_not_none():
    result = extract.extract(FIXTURES / "acceptance_ce_only.pdf")
    p = proposals.decide(result.text, "datasheet")
    assert p.status == "Unknown"


def test_an_unreadable_file_degrades_with_a_message(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not really a pdf")
    result = extract.extract(broken)
    assert result.empty and result.warnings


def test_missing_ocr_engine_says_so_instead_of_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "ocr_available", lambda: (False, extract.OCR_MISSING_MESSAGE))
    image = tmp_path / "plate.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0 not a real jpeg")
    result = extract.extract(image)
    assert result.empty
    assert "Tesseract is not installed" in result.warnings[0]


def test_an_empty_extraction_warns_rather_than_proposing_confidently():
    p = proposals.decide("", "datasheet")
    assert p.status == "Unknown"
    assert any("No text could be read" in w for w in p.warnings)


# ── filing ─────────────────────────────────────────────────────────────────

@pytest.fixture
def drive(tmp_path):
    config_module.override_config(drive_root=tmp_path / "Drive")
    yield tmp_path / "Drive" / "Technical"
    config_module.reset_config()


def test_files_land_in_the_right_branch_of_the_drive_tree(tmp_path, drive):
    source = tmp_path / "x.pdf"
    source.write_bytes(b"data")
    assert "Chargers/AC Chargers/Alfen" in filing.store(source, "datasheet", "Alfen", root=drive).relative.replace("\\", "/")
    assert "Evidence/Photos/Alfen" in filing.store(source, "photo", "Alfen", root=drive).relative.replace("\\", "/")
    assert "Evidence/Conformity/Alfen" in filing.store(source, "doc", "Alfen", root=drive).relative.replace("\\", "/")
    assert "Meters/Inepro" in filing.store(source, "meter", "Inepro", root=drive).relative.replace("\\", "/")


def test_dc_datasheets_file_under_dc(tmp_path, drive):
    source = tmp_path / "x.pdf"
    source.write_bytes(b"data")
    stored = filing.store(source, "datasheet", "ABB", charge_type="DC", root=drive)
    assert "DC Chargers" in stored.relative


def test_a_revised_document_never_overwrites_the_captured_one(tmp_path, drive):
    source = tmp_path / "x.pdf"
    source.write_bytes(b"first revision")
    first = filing.store(source, "datasheet", "Alfen", "A_B_datasheet.pdf", root=drive)

    source.write_bytes(b"second revision")
    second = filing.store(source, "datasheet", "Alfen", "A_B_datasheet.pdf", root=drive)

    assert second.path.endswith("_v2.pdf")
    assert Path(first.path).read_bytes() == b"first revision"   # the original claim's evidence
    assert first.sha256 != second.sha256


def test_an_identical_re_upload_is_recognised_not_duplicated(tmp_path, drive):
    source = tmp_path / "x.pdf"
    source.write_bytes(b"same bytes")
    first = filing.store(source, "datasheet", "Alfen", "A_B_datasheet.pdf", root=drive)
    again = filing.store(source, "datasheet", "Alfen", "A_B_datasheet.pdf", root=drive)
    assert again.duplicate_of and again.path == first.path


def test_every_stored_file_records_a_sha256(tmp_path, drive):
    source = tmp_path / "x.pdf"
    source.write_bytes(b"data")
    stored = filing.store(source, "datasheet", "Alfen", root=drive)
    assert len(stored.sha256) == 64
    assert stored.sha256 == extract.sha256(Path(stored.path))


def test_a_brand_with_awkward_characters_still_files(tmp_path, drive):
    source = tmp_path / "x.pdf"
    source.write_bytes(b"data")
    stored = filing.store(source, "datasheet", "ABL (=Wallbox)", root=drive)
    assert Path(stored.path).exists()


def test_a_retagged_file_moves_to_where_it_belongs(tmp_path, drive):
    """Files are stored before anyone says what they are; correcting that moves them."""
    source = tmp_path / "upload.pdf"
    source.write_bytes(b"datasheet bytes")
    provisional = filing.store(source, "datasheet", "Unsorted", "Unknown__datasheet.pdf", root=drive)
    assert "Unsorted" in provisional.relative

    moved = filing.refile(provisional, "datasheet", "Alfen", "Eve Single Plus", root=drive)
    assert "Alfen" in moved.relative
    assert moved.relative.endswith("Alfen_EveSinglePlus_datasheet.pdf")
    assert Path(moved.path).read_bytes() == b"datasheet bytes"
    assert not Path(provisional.path).exists()      # exactly one copy, not two
    assert moved.sha256 == provisional.sha256


def test_refiling_a_photo_moves_it_into_the_evidence_tree(tmp_path, drive):
    source = tmp_path / "plate.jpg"
    source.write_bytes(b"image bytes")
    provisional = filing.store(source, "datasheet", "Unsorted", "x.jpg", root=drive)
    moved = filing.refile(provisional, "photo", "Alfen", "Eve", root=drive)
    assert "Evidence/Photos/Alfen" in moved.relative.replace("\\", "/")
