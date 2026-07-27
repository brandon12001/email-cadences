# Email Cadence Tracker

This app does **not** send email. It does three things:

1. Tracks which step of the sequence every prospect is on.
2. Uses Claude to research each company and write a tailored three-email sequence.
3. Exports a daily merge CSV for Word and Outlook.

Sending happens in Word and Outlook via `Cadence_Sender_Macro.vba.txt`. That is
deliberate: Outlook is what applies the Salesforce BCC and your real signature,
which carries the regulatory footer. Nothing leaves the app.

## Deploy

1. Create a **public** GitHub repo (for example `email-cadences`).
2. Upload to the repo root: `app.py`, `cadence_engine.py`, `requirements.txt`,
   `.gitignore`.
3. share.streamlit.io, New app, paste the GitHub URL to `app.py` (open the file
   on github.com and copy the address bar).
4. Advanced settings, Secrets:

```
APP_PASSWORD = "pick-a-password"
ANTHROPIC_API_KEY = "sk-ant-..."
ANTHROPIC_MODEL = "claude-haiku-4-5"
ANTHROPIC_WEB_SEARCH = "true"
```

There is no SMTP configuration. Do not add any.

5. Deploy, open the URL, enter your password.

## Daily loop

1. **Flag replies.** Send today tab. Paste addresses or upload a CSV export from
   Outlook. Flagging stops that person only. Colleagues at the same company stay
   in their own sequence.
2. **Tailor the next due contacts.** One Anthropic request per contact writes and
   caches all three emails.
3. **Review and download the merge CSV.**
4. **Run the Word macro.** It applies the Salesforce BCC and your signature.
5. **Come back and advance the batch,** but only if the macro reported every send
   as successful. If any failed, do not advance.
6. **Download the state backup** when the app asks.

## Flagging replies in bulk

Paste addresses one per line, or upload a CSV. The parser is forgiving: it
accepts bare addresses, `Sarah Jones <sarah@company.com>`, and comma or
semicolon separated lists.

For a CSV it looks for a column called Email, From, `From: (Address)`, Sender or
similar. If it cannot find one, it reads every address in the file. To export
from Outlook: File, Open and Export, Import/Export, Comma Separated Values.

After flagging you get three numbers: flagged, already stopped, and not found.
**Read the not-found list.** A reply from an alias, a colleague, or a forwarded
thread will not match anyone in the tracker, and those need handling by hand.

Flagged contacts are excluded from every future merge CSV. The record is kept
rather than deleted, so re-uploading your contact list cannot resurrect them and
email them again.

## Uploading contacts

Contacts tab. CSV with `name`, `email`, `company`, and optionally `title`,
`website` and `ammo`. Re-uploading enriches existing contacts rather than
duplicating them, so overlapping uploads are safe.

## State, and why the backup nag exists

Everything lives in `cadence_state.json`: each contact's step, their status, and
their cached tailored copy. Streamlit Community Cloud storage can reset on
redeploy.

If that happens without a backup you lose every contact's position in the
sequence, and there is no way to reconstruct it from Outlook. The app now raises
a red banner after any tailoring or advance and will not clear it until you
download the backup. Do not ignore it.

## The sequence

Three steps, waits of 0, 3 and 4 days, so day 0, day 3, day 7. Editable on the
Cadence tab. Those steps are strategy briefs for Claude, not the final emails.
Only Claude-tailored contacts can enter the merge CSV.

## Known limits (deliberate)

- No automatic reply detection. Flagging repliers is your job, before each run.
- The app cannot know what Outlook actually sent, which is why advancing the
  batch is a manual confirmation.
- Email bodies end at `Best,`. Outlook inserts the real signature underneath.
