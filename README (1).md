# Email Cadence Platform

Automated follow-up sequences with manual reply control. Contacts get email 1,
then email 2 after a wait, then email 3. You flag anyone who replies before
each run and they are stopped for good. Fixes the Word mail-merge gap:
tailoring AND follow-ups, with you in full control of what goes out.

## Deploy (same dance as the CH platform)

1. Create a new **public** GitHub repo (e.g. `email-cadences`).
2. Upload these four files to the repo root: `app.py`, `cadence_engine.py`,
   `requirements.txt`, `.gitignore`.
3. share.streamlit.io -> New app -> paste the GitHub URL to `app.py`
   (open the file on github.com and copy the address bar, same trick as before).
4. Advanced settings -> Secrets:

```
APP_PASSWORD = "pick-a-password"
SF_BCC = "your-long-emailtosalesforce-address"
SMTP_HOST = "smtp.office365.com"
SMTP_PORT = "587"
SMTP_USER = "brandon.ellis@lumonpay.com"
SMTP_PASS = "an-app-password-from-your-microsoft-account"
```

The first two are required. The SMTP four enable automatic sending; leave
them out and the app runs in draft mode (it writes every due email for you to
paste into Outlook - still fully sequenced and tracked).

5. Deploy. Open the URL, enter your password.

## Daily rhythm (2-10 minutes)

1. Scan your Outlook inbox for replies from anyone in a sequence.
2. App -> Send today tab -> **flag each replier** (stops their sequence).
3. Hit **Run: send due steps**. Throttled sends, SF BCC on every email.

## Uploading leads

Contacts tab -> CSV with columns: `name, email, company` and optionally
`ammo` (a fact line from the CH call sheet that opens email 1). Duplicates
are skipped automatically, so overlapping uploads are safe.

## The sequence

Three steps pre-loaded (strategy-led, never price), waits of 0 / 3 / 4 days,
all editable on the Cadence tab with live preview against a real contact.
Merge fields: `{first_name}` `{company}` `{ammo_line}`.

## Rules built in

- Opt-out line on every email; a "no thanks" reply = flag and stop.
- Regulatory footer comes from your Outlook signature (SMTP sends may not
  carry the Outlook signature - check your first sent item; if missing, ask
  Claude to add a signature block setting).
- Throttled sending (15s gaps, 40/day default). Do not crank to blast levels.

## Known limits (deliberate)

- No automatic reply detection - flagging repliers before each run is YOUR
  job. The banner above the send button reminds you.
- Sends fire when you press the button, not on a schedule.
- State lives in a JSON file that can reset on redeploys: use Download/
  Restore state on the Settings tab after big changes.
