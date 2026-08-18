# Zeres MID Register

Internal knowledge base for EV charger and kWh-meter MID certification, used by the Zeres
helpdesk to answer one question: **for a given charger brand and model, is there a
MID-certified meter, and what is the evidence?**

The register is an Excel workbook — that is deliberate, see [CLAUDE.md](CLAUDE.md). This
app is a local web UI over it, plus a datasheet downloader and a document intake pipeline.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m migrate.migrate_tracker      # one-time: builds data/Zeres_MID_Register.xlsx
./run.sh                               # starts the app and opens a browser
```

Requires Python 3.11+. OCR of scanned documents additionally needs Tesseract
(`brew install tesseract` / `apt install tesseract-ocr`); without it the intake still
works and says so rather than failing.

## Configuration

`config.toml` holds paths and knobs. The one you will want to change is the Drive root:

```toml
[drive]
root = "/Users/you/Library/CloudStorage/GoogleDrive-you@zeres.nl/My Drive"
```

`ZERES_REGISTER_PATH` and `ZERES_DRIVE_ROOT` override it per machine. Secrets, if any are
ever needed, go in `.env` — see `.env.example`. None are required today.

## Layout

```
app/
  config.py       config.toml + .env
  schema.py       sheet columns and the five-value MID vocabulary
  storage.py      load() / save() / backup() — the ONLY module that knows about .xlsx
  domain.py       eligibility, IDs, Drive paths, note handling
  manifest.py     the download queue and gap detection
migrate/
  mapping.py           old Yes/No/Maybe -> the five statuses, with its reasoning
  migrate_tracker.py   one-time migration (already run)
data/
  Zeres_MID_Register.xlsx   the register
  source/                   the original tracker, manifest.csv and the UI prototype
backups/          last 30 saves, newest first
tests/
```

## The register

| Sheet | Rows | What it is |
|---|---|---|
| Read Me | — | provenance, carried over from the original tracker |
| Chargers | 380 | one row per brand/model, IDs `chg_0001`… |
| Meters | 4 | the components that actually carry certification, `mtr_0001`… |
| Conflicts | 0 | rows where two source systems disagreed; empty until that data arrives |
| Manifest | 265 | the datasheet download queue |
| Change Log | 384 | append-only audit trail; currently the migration's status remaps |

Every row currently has `Review Needed` set: the seed data was never
manufacturer-verified, so nothing is safe to quote to a client until someone confirms it
against a primary source and clears the flag.

### Status distribution after migration

| Status | Rows | |
|---|---|---|
| Integrated | 137 | eligible as sold |
| Optional | 62 | **eligible** — check the individual unit |
| External | 18 | **eligible** if the external meter is fitted |
| None | 109 | not eligible as sold |
| Unknown | 58 | needs research |

217 of 384 rows are ERE-eligible in some form. `Optional` and `External` are not
rejections — see CLAUDE.md before writing anything that groups them with `None`.

## Editing

Any row can be edited from the detail drawer, and new charger and meter rows added.
Every change appends to the **Change Log** — timestamp, OS username, row ID, field, old
value, new value, and reason. The log is append-only; nothing rewrites it.

Two rules are enforced in the API rather than the UI, so they hold however the row is
reached:

- **Changing a MID status requires a source or a note.** An unexplained status change is
  what an NEa audit would query. The request is refused with a 422.
- **Notes are appended, never overwritten.** They carry quoted source language, so the
  drawer shows existing notes read-only and offers a separate "append a note" box.

## Conflicts

Rows where the research tracker and the Zite dashboard disagreed. Both sources are shown
side by side with their reasoning; a person picks one and states why. There is no
auto-resolve anywhere — no "prefer the newer source", no tie-break, no bulk apply.

A conflict is flagged **opposed** when one side says eligible (Integrated/Optional/
External) and the other says None. Those are the serious ones: the answer a client got
depended on which system the helpdesk happened to open.

Resolving writes the chosen status onto the charger row, clears the row's `Conflict`
marker, appends both sides' positions to the notes, and logs it all. It deliberately does
**not** clear `Review Needed` — adjudicating a source disagreement is not the same as
verifying the row against a primary source.

> The Conflicts sheet in this workbook is **empty**. The feature is built and tested
> against synthetic rows, ready for the 25 real disagreements when they arrive.

## Manifest and the downloader

The Manifest tab lists the download queue, with filtering, add and remove, and gap
detection prominently at the top. "Queue all gaps" closes them in one action.

`python -m app` serves a downloader that replaces `sync_datasheets.ps1`:

- **idempotent** — a file already on disk and non-empty is skipped; a 0-byte file from a
  previous failed run is re-fetched rather than trusted
- **concurrent**, capped by `[downloader].max_concurrent`
- **retries with exponential backoff** on transport errors, 5xx and 429
- **sends a real browser User-Agent** — several vendor CDNs 403 anything else
- **writes via a `.part` file** so an interrupted fetch never leaves a half-file that the
  next run would mistake for a completed download
- **empty-URL rows are skipped silently**, reported as `no-url`, never as failures

Per-file results come back into the queue table as you watch.

## Safety properties

- **Never writes in place.** Every save backs up first, writes to a temp file, then
  atomically replaces the original. A crash leaves either the old file or the new one.
- **Refuses to clobber.** If the workbook changed on disk since it was loaded — someone
  editing in Excel — the save raises rather than overwriting their work.
- **Loses nothing.** Sheets the app does not own are carried through untouched, and
  columns added by hand survive a round trip. Both are asserted by tests.

## Tests

```bash
python -m pytest tests/ -q
```

120 tests covering: the storage round trip and atomicity, backup rotation, stale-file
refusal, gap detection against the three real known gaps, the seed-vocabulary mapping
including its negation and CE/Eichrecht traps, the status vocabulary, and the editing
rules above — that a status change without a reason is refused, that the change log is
append-only, that notes survive an edit, and that a deleted row's ID is never reissued.
Conflicts are covered with synthetic rows (opposed detection, refusal to resolve without a
reason, no silent re-decision). The downloader runs against a real local HTTP server rather
than mocks, covering idempotency, the 0-byte case, retry-on-503, and empty-URL handling.

Note: the downloader has **not** been exercised against real manufacturer CDNs — the
sandbox this was built in blocks outbound connections to them. Its behaviour on real URLs
is covered by the local-server tests; the first real run should be spot-checked.

## Migration note

The workbook this was built from (`Zeres_EV_Charger_MID_Meter_Tracker.xlsx`) used an older
schema: one combined sheet, no stable IDs, and a Yes/No/Maybe vocabulary. `migrate/`
converts it. The mapping is not a lookup table — 66 rows had note text that contradicted
their seed value, including 15 seeded "No" that in fact offer an optional or external MID
meter and would otherwise have been read as ineligible. `migrate/mapping.py` explains
each rule; `python -m migrate.migrate_tracker --dry-run` prints every reclassification.
