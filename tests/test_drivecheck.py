"""The Drive folder check.

Pointing the app at the wrong folder looks exactly like it working: files get
written, the UI says "stored", and nothing reaches Drive. These tests cover the
mistakes that actually happen, not just "does the path exist".
"""

import pytest

from app import config as config_module
from app import drivecheck


@pytest.fixture
def drive(tmp_path):
    """A Drive root outside the project, so it is not read as the placeholder."""
    yield tmp_path
    config_module.reset_config()


def status_for(root):
    config_module.override_config(drive_root=root)
    return drivecheck.check()


def test_the_shipped_placeholder_is_flagged(drive):
    """Files land inside the app folder and never sync. Say so."""
    from app.config import PROJECT_ROOT
    result = status_for(PROJECT_ROOT / "data" / "drive")
    assert result.level == drivecheck.WARNING
    assert "not on Drive" in result.headline
    assert "config.toml" in result.fix


def test_a_missing_folder_is_an_error(drive):
    result = status_for(drive / "nowhere")
    assert result.level == drivecheck.ERROR
    assert "does not exist" in result.headline
    assert "Google Drive for desktop" in " ".join(result.details)


def test_pointing_at_the_technical_folder_itself_is_caught(drive):
    """The real-world mistake: G:\\...\\Technical\\Technical is the tree, and the
    app appends Technical of its own, so configuring the inner one writes a
    third level that nobody is looking at."""
    technical = drive / "Operations" / "Technical" / "Technical"
    (technical / "Chargers").mkdir(parents=True)
    (technical / "Meters").mkdir()

    result = status_for(technical)
    assert result.level == drivecheck.ERROR
    assert "one level too deep" in result.headline
    assert str(technical.parent) in result.fix       # tells them the right answer


def test_the_correct_parent_passes(drive):
    technical = drive / "Operations" / "Technical" / "Technical"
    (technical / "Chargers").mkdir(parents=True)
    (technical / "Meters").mkdir()

    result = status_for(technical.parent)
    assert result.ok
    assert str(technical) in result.headline
    assert "Chargers" in " ".join(result.details)


def test_a_root_with_no_technical_folder_yet_is_only_a_warning(drive):
    """It is created on first use, so this is a caution, not a failure."""
    root = drive / "SomeDrive"
    root.mkdir()
    result = status_for(root)
    assert result.level == drivecheck.WARNING
    assert "No Technical folder" in result.headline


def test_a_technical_folder_with_none_of_the_expected_subfolders_warns(drive):
    root = drive / "SomeDrive"
    (root / "Technical").mkdir(parents=True)
    result = status_for(root)
    assert result.level == drivecheck.WARNING
    assert "expected subfolders" in result.headline


def test_a_read_only_shared_drive_is_reported_as_such(drive):
    """View-only access to a Shared drive looks like a normal folder but rejects writes."""
    root = drive / "SharedDrive"
    (root / "Technical" / "Chargers").mkdir(parents=True)
    (root / "Technical").chmod(0o500)
    try:
        result = status_for(root)
        if result.level == drivecheck.OK:
            pytest.skip("filesystem ignores the read-only bit for this user")
        assert result.level == drivecheck.ERROR
        assert "not writable" in result.headline
        assert "view-only" in " ".join(result.details)
    finally:
        (root / "Technical").chmod(0o700)


def test_the_status_survives_a_round_trip_to_the_ui(drive):
    technical = drive / "D" / "Technical"
    (technical / "Meters").mkdir(parents=True)
    payload = status_for(drive / "D").as_dict()
    assert set(payload) == {"level", "root", "technical", "headline", "details", "fix"}
    assert payload["technical"] == str(technical)


def test_the_startup_banner_names_the_problem_and_the_fix(drive):
    text = drivecheck.describe(status_for(drive / "nowhere"))
    assert "XX" in text and "does not exist" in text and "Fix:" in text
