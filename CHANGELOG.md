# Changelog

## Current: tracker-v3-merge-csv-only

The app no longer sends email. It tracks sequence position and exports the
daily merge CSV. Word and Outlook do the sending.

- Removed the SMTP send path from `app.py` and `smtp_send` from
  `cadence_engine.py`. Removed SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS and
  SF_BCC from secrets handling.
- This also closes a compliance hole: the SMTP path built emails ending at
  "Best," with no name and no regulatory footer, because it never had the
  Outlook signature the Word path relies on. If those secrets had ever been
  set, every SMTP send would have gone out non-compliant.
- Added bulk reply flagging. Paste addresses or upload a CSV export. Replaces
  the one-at-a-time selectbox.
- Reply parser accepts bare addresses, "Name <addr>", comma and semicolon
  separated lists, and CSVs with Email, From, "From: (Address)" or Sender
  columns. Falls back to scanning the whole file. Handles UTF-8 BOM.
- Flagging stops that person only. Colleagues at the same company are
  unaffected.
- Flagged contacts are marked replied, not deleted, so re-uploading the contact
  CSV cannot resurrect them.
- Reply flagging reports flagged, already stopped and not found. The not-found
  list is shown so aliases and forwarded threads can be handled by hand.
- Contacts tab now defaults to active only.
- Header shows active, replied, finished and total counts.
- Added a red state-backup banner that appears after any tailoring or advance
  and does not clear until the backup is downloaded. State durability is the
  main operational risk now that the app is the only record of sequence
  position.
- Bumped ENGINE_API_VERSION to catch mixed deployments.
- Extended the smoke tests to cover address parsing, CSV parsing, bulk
  flagging, colleague isolation and the absence of the SMTP path.

## Previous: Anthropic strategy-first tailoring v2

- Added Anthropic company research and three-email generation.
- Added optional one-search-per-contact web research.
- Added cached tailored sequences.
- Added role, website, company domain and ammo context.
- Added batch limits for cost control.
- Added regeneration option for previously tailored contacts.
- Added mandatory review before CSV export.
- Blocked untailored contacts from export.
- Repositioned all model instructions around hedging strategy, margin certainty and flexibility.
- Added rejection of known generic and price-led phrases.
- Added a strategy-language threshold.
- Retained a model name secret so account-specific model access can be changed without editing code.

## Deployment and migration fixes

- Added `ENGINE_API_VERSION` and required-function checks to detect mixed `app.py` and `cadence_engine.py` deployments.
- Migrated legacy templates and removed manual signatures.
- Added safe state normalization.
- Re-uploading a CSV now enriches existing contacts instead of skipping useful new fields.
- Added invalid email filtering.

## Word and Outlook fixes

- Removed deprecated pandas JSON serialization that caused the original Streamlit crash.
- Exported merge CSV without a BOM.
- Added BOM stripping in VBA as a second line of defence.
- Replaced Outlook `.Body` insertion with the Outlook Word editor to preserve HTML signatures.
- Added quoted-CSV parsing and literal `\n` line restoration.
- Added clear send failure reporting.
- Email bodies now end at `Best,` and do not repeat Brandon's name or Lumon.

## State and workflow improvements

- Added state download and restore.
- Added manual reply stopping.
- Added send logs.
- Added a warning not to advance partially failed batches.
