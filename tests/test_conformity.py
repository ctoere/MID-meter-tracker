"""Conformity hunting and fan-out.

A declaration is the strongest evidence the register can hold, which makes
attaching one to the wrong row the most damaging mistake in this module.
Most of what follows tests restraint.
"""

import pytest
from fastapi.testclient import TestClient

from app import conformity, server, storage


@pytest.fixture
def client(sandbox):
    server.reload_register()
    server._domain_overrides.clear()
    with TestClient(server.app) as c:
        yield c


CHARGERS = [
    {"ID": "chg_0001", "Brand": "Alfen", "Model": "Eve Single Pro-line", "MID Status": "Integrated",
     "Certificate Link": "", "Datasheet Link": "https://alfen.com/x.pdf"},
    {"ID": "chg_0002", "Brand": "Alfen", "Model": "Eve Mini (ICU)", "MID Status": "Optional",
     "Certificate Link": "", "Datasheet Link": "https://eu-assets.contentstack.com/y.pdf"},
    {"ID": "chg_0003", "Brand": "Wallbox", "Model": "Pulsar", "MID Status": "External",
     "Certificate Link": "", "Datasheet Link": ""},
    {"ID": "chg_0004", "Brand": "Wallbox", "Model": "Pulsar Plus", "MID Status": "External",
     "Certificate Link": "", "Datasheet Link": ""},
    {"ID": "chg_0005", "Brand": "Besen", "Model": "BS20", "MID Status": "None",
     "Certificate Link": "", "Datasheet Link": ""},
    {"ID": "chg_0006", "Brand": "Alfen", "Model": "Twin 5", "MID Status": "Integrated",
     "Certificate Link": "https://alfen.com/already.pdf", "Datasheet Link": ""},
]


# ── the backlog ────────────────────────────────────────────────────────────

def test_only_eligible_rows_need_a_declaration():
    """A charger with no MID metering does not need a MID declaration."""
    ids = {r["ID"] for r in conformity.backlog(CHARGERS)}
    assert "chg_0005" not in ids          # None
    assert "chg_0006" not in ids          # already has one
    assert ids == {"chg_0001", "chg_0002", "chg_0003", "chg_0004"}


def test_targets_are_grouped_by_brand_busiest_first():
    targets = conformity.targets(CHARGERS)
    assert [t.brand for t in targets] == ["Alfen", "Wallbox"]
    assert targets[0].count == 2


def test_domain_is_derived_from_a_datasheet_link():
    assert conformity.derive_domain("Alfen", CHARGERS)[0] == "alfen.com"


def test_a_cdn_or_reseller_host_is_not_taken_as_the_manufacturer():
    """A link to a CDN says nothing about where the manufacturer publishes."""
    only_cdn = [{"Brand": "X", "Model": "M", "MID Status": "Integrated", "Certificate Link": "",
                 "Datasheet Link": "https://eu-assets.contentstack.com/a.pdf"}]
    assert conformity.derive_domain("X", only_cdn)[0] == ""
    for host in ("manualslib.com", "cdn.shopify.com", "elaad.nl"):
        rows = [{"Brand": "X", "Model": "M", "MID Status": "Integrated", "Certificate Link": "",
                 "Datasheet Link": f"https://{host}/a.pdf"}]
        assert conformity.derive_domain("X", rows)[0] == "", host


def test_a_confirmed_domain_overrides_the_guess():
    targets = conformity.targets(CHARGERS, {"Alfen": "alfen.nl"})
    alfen = next(t for t in targets if t.brand == "Alfen")
    assert alfen.domain == "alfen.nl" and not alfen.domain_is_guess


# ── the searches ───────────────────────────────────────────────────────────

def test_the_first_search_is_the_highest_signal_one():
    links = conformity.search_links("Alfen", "alfen.com")
    assert "site%3Aalfen.com" in links[0]["url"]
    assert "2014%2F32%2FEU" in links[0]["url"]


def test_searches_cover_the_languages_this_market_publishes_in():
    joined = " ".join(l["url"] for l in conformity.search_links("Mennekes", "mennekes.org"))
    assert "verklaring" in joined            # NL
    assert "Konformit" in joined             # DE


def test_searches_work_without_a_domain():
    links = conformity.search_links("Unknownbrand")
    assert links and all(l["url"].startswith("http") for l in links)


# ── fan-out ────────────────────────────────────────────────────────────────

def test_one_declaration_fans_out_across_a_product_family():
    matches = conformity.match_rows(CHARGERS, "Alfen", "Eve Single Pro-line; Eve Mini")
    assert {m["id"] for m in matches} == {"chg_0001", "chg_0002"}
    assert matches[0]["confidence"] == "exact"


def test_a_declaration_never_reaches_another_brand():
    matches = conformity.match_rows(CHARGERS, "Alfen", "Pulsar Plus; Eve Single Pro-line")
    assert {m["brand"] for m in matches} == {"Alfen"}


def test_a_more_specific_declaration_is_flagged_rather_than_trusted():
    """A declaration for 'Pulsar Plus' does not cover the base 'Pulsar'.

    Attaching it would manufacture evidence, so the row is surfaced at the
    weakest confidence and the UI leaves it unticked.
    """
    matches = {m["id"]: m for m in conformity.match_rows(CHARGERS, "Wallbox", "Pulsar Plus")}
    assert matches["chg_0004"]["confidence"] == "exact"
    assert matches["chg_0003"]["confidence"] == "check"
    assert "more specific" in matches["chg_0003"]["reason"]


def test_a_generic_token_does_not_match_the_whole_range():
    assert conformity.match_rows(CHARGERS, "Wallbox", "Pro") == []
    assert conformity.match_rows(CHARGERS, "Alfen", "S") == []


def test_a_row_that_already_has_a_certificate_is_shown_as_such():
    matches = conformity.match_rows(CHARGERS, "Alfen", "Twin 5")
    assert matches[0]["currentCertificate"].endswith("already.pdf")


@pytest.mark.parametrize("covered,expected", [
    ("A, B", ["A", "B"]),
    ("A; B", ["A", "B"]),
    ("A and B", ["A", "B"]),
    ("A en B", ["A", "B"]),
])
def test_model_lists_are_split_the_way_documents_write_them(covered, expected):
    assert conformity.split_models(covered) == expected


# ── recording, through the API ─────────────────────────────────────────────

DOC_WITH_DIRECTIVE = {"certificate_number": "T10402", "issuing_body": "NMi",
                      "directive_cited": True, "models_covered": ["Eve Single Pro-line"]}
DOC_WITHOUT = {"certificate_number": "ABC-1", "issuing_body": "TUV",
               "directive_cited": False, "models_covered": ["Eve Single Pro-line"]}


def test_backlog_endpoint_reports_the_real_numbers(client):
    body = client.get("/api/conformity/backlog").json()
    assert body["stats"]["outstanding"] == 211
    assert body["stats"]["brands"] == 59
    assert body["targets"][0]["count"] >= body["targets"][-1]["count"]
    assert body["targets"][0]["searches"]


def test_recording_a_declaration_links_the_chosen_rows(client):
    target = storage.load().chargers[0]
    res = client.post("/api/conformity", json={
        "brand": target["Brand"], "doc": DOC_WITH_DIRECTIVE,
        "link": "Technical/Evidence/Conformity/X/doc.pdf", "applyTo": [target["ID"]]})
    assert res.status_code == 200
    assert res.json()["linked"] == [target["ID"]]

    reloaded = storage.load()
    assert reloaded.charger(target["ID"])["Certificate Link"].endswith("doc.pdf")
    assert len(reloaded.conformity) == 1
    assert reloaded.conformity[0]["Directive Cited"] == "2014/32/EU"


def test_a_declaration_without_the_directive_is_filed_but_never_linked(client):
    """It looks official and says nothing about metrology. Keep it; don't cite it."""
    target = storage.load().chargers[0]
    res = client.post("/api/conformity", json={
        "brand": target["Brand"], "doc": DOC_WITHOUT,
        "link": "Technical/Evidence/Conformity/X/lvd.pdf", "applyTo": [target["ID"]]})
    assert res.status_code == 200
    assert res.json()["linked"] == []
    assert res.json()["directiveCited"] is False

    reloaded = storage.load()
    assert reloaded.charger(target["ID"])["Certificate Link"] == ""   # untouched
    record = reloaded.conformity[0]
    assert record["Directive Cited"] == ""
    assert "NOT MID evidence" in record["Review Needed"]              # filed, and flagged


def test_linking_is_logged_with_the_certificate_as_its_reason(client):
    target = storage.load().chargers[0]
    client.post("/api/conformity", json={
        "brand": target["Brand"], "doc": DOC_WITH_DIRECTIVE,
        "link": "x.pdf", "applyTo": [target["ID"]]})
    entries = [e for e in storage.load().change_log
               if e["Row ID"] == target["ID"] and e["User"] != "migration"]
    assert entries and entries[-1]["Field"] == "Certificate Link"
    assert "T10402" in entries[-1]["Reason"]
    assert "2014/32/EU" in entries[-1]["Reason"]


def test_a_confirmed_domain_survives_into_the_searches(client):
    client.post("/api/conformity/domain", json={"brand": "Alfen", "domain": "https://www.alfen.com/"})
    target = next(t for t in client.get("/api/conformity/backlog").json()["targets"]
                  if t["brand"] == "Alfen")
    assert target["domain"] == "alfen.com"       # scheme and www stripped
    assert target["domainIsGuess"] is False


def test_the_register_exports(client):
    client.post("/api/conformity", json={"brand": "Alfen", "doc": DOC_WITH_DIRECTIVE, "applyTo": []})
    body = client.get("/api/conformity/export").json()
    assert body["columns"][0] == "ID"
    assert len(body["rows"]) == 1
