# CLAUDE.md — Zeres MID Register

Domain rules for this codebase. These are compliance rules, not preferences.
Read this before changing anything that touches MID status, eligibility, or evidence.

## What this tool is for

Zeres is a Dutch ERE *inboekdienstverlener*. We register EV charging kWh with the
Nederlandse Emissieautoriteit (NEa) under the Register Energie voor Vervoer, sell the
resulting emission-reduction units, and pay the proceeds back to the driver.

A charge point only qualifies if its kWh meter is MID-certified under EU Directive
2014/32/EU. So this tool answers exactly one question:

> For a given charger brand and model, is there a MID-certified meter, and what is the
> evidence?

A wrong row means either kWh booked into the REV that should not have been, or a client
wrongly told they are ineligible. Every status needs traceable evidence, and the tool
must make uncertainty **visible** rather than smoothing it over.

Audience is internal: our own staff and helpdesk, roughly 20 people. No public access,
no customer login, no manufacturer self-service, no authentication.

## The five MID statuses — and the one that costs money

| Status | Meaning | Commercial consequence |
|---|---|---|
| `Integrated` | MID meter built in as standard | Eligible as sold |
| `Optional` | Available as a variant or paid option | **Eligible** — the individual unit must be checked |
| `External` | Uses a separate external MID meter | **Eligible** if that meter is actually fitted |
| `None` | No MID metering | Not eligible as sold |
| `Unknown` | Not established | Needs research |

No other values exist. `schema.validate_status()` enforces this and the tests assert it.

**`Optional` and `External` are not rejections.** Both mean "eligible, verify the unit".
Collapsing either into `None` is the most expensive error this tool can make: it tells a
paying customer they do not qualify when in fact they do. Never render them in a way that
reads as a no — no red, no strikethrough, no grouping under "not eligible".

**Never default a row to `None`.** Absence of evidence is `Unknown`. `None` is a positive
claim that a source ruled MID out, and it needs the same evidence any other claim needs.

## Evidence rules

**Never infer MID from a CE mark.** Every electrical product sold in the EU carries CE.
It covers safety and EMC, not metrology. This is the single most common false positive on
this job. A document that mentions CE but no metrology marking yields `Unknown`, never
`Integrated`.

**Eichrecht / PTB / BAM is not MID.** German calibration law is a related but separate
regime. Record it in its own field; never let it satisfy a MID claim. The migration
downgrades any row whose only metrology language is Eichrecht to `Unknown`.

**A photo of a charger's exterior nameplate is not evidence of absence.** On most
wallboxes the meter sits behind the cover, so the outside plate carries no metrology
marking either way. An exterior photo yields `Unknown`, never `None`. The intake flow must
ask what surface a photo shows and apply this rule.

**A declaration of conformity is stronger evidence than a datasheet** — it names the
notified body and the models in scope. But a DoC that does not cite 2014/32/EU is not MID
evidence at all. Extract the certificate number, issuing body, directive cited and models
covered, and say plainly when the directive is absent.

**The meter carries the certification, not the charger.** A charger row should point at a
meter row wherever the meter is identified.

### MID markings worth detecting

- Supplementary metrology marking: `M` followed by two digits — the year it was affixed,
  typically in a rectangle, e.g. `M 26`
- A four-digit notified body number immediately after it, e.g. `0122`
- `MI-003` — the MID category for active electrical energy meters
- Accuracy class A/B/C under EN 50470-3. Class 1/2 under IEC 62053 is the older,
  **non-MID** scheme — do not accept it as MID evidence
- Phrases: `MID`, `MID-certified`, `MID-gecertificeerd`, `2014/32/EU`

## Data rules

**`Review Needed` non-empty means the row is not safe to quote to a client.** Surface it
everywhere the row appears — table, drawer, exports, search results.

**Notes carry quoted source language, not paraphrase.** Preserve existing notes when
editing: append, never overwrite (`domain.append_note`). Losing an earlier quote to make
room for a newer one destroys the evidence trail.

**IDs are stable.** `chg_0001`, `mtr_0001`, `cfl_0001`. Never renumber, never reuse — a
freed ID must not be handed to different hardware (`domain.next_id` takes max+1, not
count+1).

**Many "brands" are resellers.** Several rows are CPOs selling another manufacturer's
hardware white-labelled (50five/Shell, CoolBlue/BlueBuilt/Peblar, ABL/Wallbox). When
adding a brand, note the relationship rather than duplicating the other brand's rows.

**Editing a MID status requires a source or a note.** An unexplained status change is
exactly what an NEa audit would query. The Change Log is append-only.

**Conflicts are never auto-resolved,** and intake proposals are never auto-applied. A
human decides; the tool only presents the evidence side by side.

## Architecture constraints

**The spreadsheet is the database.** This is deliberate, not technical debt. No Postgres,
no SQLite, no ORM. Do not "clean this up" by migrating to a database.

**All persistence lives in `app/storage.py`.** It is the only module that knows the
register is an `.xlsx` file; everything above it works with plain lists of dicts. The
interface is `load()`, `save()`, `backup()`. We may move the file into Google Sheets or
SharePoint later, and that must mean editing one file.

**Writes are never in place.** The workbook lives in a synced folder and may be open in
Excel. Every save backs up first, writes to a temp file in the same directory, then
`os.replace()`s it — atomic on the same filesystem. Last 30 backups are kept.

**Runs locally.** `python -m app` or `./run.sh`. No cloud, no Docker requirement, no
account setup. No secrets in the repo; anything sensitive comes from `.env`.

## Drive folder conventions (authoritative)

```
<DriveRoot>\Technical\Chargers\AC Chargers\<Brand>\<Filename>
<DriveRoot>\Technical\Chargers\DC Chargers\<Brand>\<Filename>
<DriveRoot>\Technical\Meters\<Brand>\<Filename>
<DriveRoot>\Technical\Evidence\Photos\<Brand>\<Filename>
<DriveRoot>\Technical\Evidence\Conformity\<Brand>\<Filename>
```

The manifest's `SubFolder` column holds the path below `Technical`, using **backslashes**.
Filename convention: `<Brand>_<ModelNoSpaces>_datasheet.pdf`, e.g.
`Alfen_EveSinglePlus_datasheet.pdf`. Almost all are PDFs; a couple are `.html` where the
manufacturer publishes no PDF.

**A manifest row with an empty `Url` is legitimate, not a bug.** Some datasheets came
directly from the manufacturer and are filed by hand. Skip them silently; never report
them as failures.

**Gap detection matters.** A register row with a datasheet link whose URL is absent from
the manifest is a gap. This has bitten Zeres twice: the register looks complete while the
download queue quietly has holes, so the file never reaches Drive. A datasheet is the
evidence behind a compliance claim and the manufacturer can revise or delete it at any
time — the copy we captured is the one that matters.

## The migration

`migrate/migrate_tracker.py` converted the original
`Zeres_EV_Charger_MID_Meter_Tracker.xlsx` (one `Master Tracker` sheet, no IDs, older
Yes/No/Maybe vocabulary) into the register schema. It is one-time and already run;
`migrate/mapping.py` documents why the mapping is not a lookup table.

Every migrated row has `Review Needed` set. The seed data was never manufacturer-verified
— the original Read Me calls it "a strong starting signal, not a manufacturer-verified
fact" — so nothing is safe to quote until a human clears the flag.

## Where the shared reading of evidence lives

`app/evidence.py` holds the patterns that decide whether text describes a MID meter as
standard, optional, or external, plus the negation handling. Both the seed migration and
the intake pipeline use it — encoding "what counts as an optional MID meter" twice is how
the two drift apart. `app/intake/markings.py` adds the metrology-marking detection on top.

Two hard-won details in there, both with regression tests:

- every optionality pattern is anchored to a MID reference (`MID`, `MI-003`, `2014/32/EU`),
  because a bare "variant" matches product-line language like "wall-mounted variant"
- negation is judged at the meaning-carrying word and does not cross a clause boundary:
  "No built-in MID; external accessory option" is External, while "No MID in any variant"
  is a rejection

## Conformity

`app/conformity.py`. A declaration of conformity is issued **per brand or product family,
not per model**, so the backlog is organised by brand and one document fans out across
every row it covers. That fan-out is the feature; the searching in front of it is manual
because no EU registry of declarations exists.

Matching a declaration to rows is deliberately asymmetric, and the asymmetry is the whole
safety property:

- declaration names `Eve Mini`, row reads `Eve Mini (ICU)` → **likely**, the document's
  name is the broader one
- declaration names `Pulsar Plus`, row reads `Pulsar` → **check only**, never confident:
  the document names a *more specific* product and the row may be different hardware

Attaching a certificate to a model it does not cover manufactures evidence, which is worse
than leaving a row unlinked for someone to do by hand. Model tokens shorter than four
normalised characters never match, or `Pro` would attach a certificate to half a range.

A declaration that does not cite 2014/32/EU is filed and listed, but never written onto a
row. `Directive Cited` empty means *not MID evidence*.

## UI

`app/static/` is the prototype (`data/source/zeres_register_console_prototype.html`) split
into files. Its layout, colour semantics and copy are the result of real iteration —
improve it, don't replace it. Colour is never the only carrier of meaning: every status
badge shows a text label beside the dot.
