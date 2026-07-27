Email Cadence Platform

This app sequences three-step follow-ups while keeping sending inside Outlook.

Files to upload to the GitHub repo root

Rename and upload:

app_fixed.py as app.py

cadence_engine_fixed.py as cadence_engine.py

requirements_fixed.txt as requirements.txt

your .gitignore

Keep Cadence_Sender_Macro_FIXED.vba.txt off the public repo because it contains your Salesforce Email-to-Salesforce address. Install it locally in Word.

Streamlit secrets

For the Word and Outlook macro route, only this is needed:

APP_PASSWORD = "pick-a-password"

The Salesforce BCC is already applied by the Word macro. SMTP secrets are optional and are not needed for the recommended workflow.

First test

Deploy the app.

Upload a CSV containing one row with your own name, email and company.

Download the one-row merge CSV.

Run SendCadenceBatch from Word.

Confirm the received email has correct paragraphs, your formatted Outlook signature, and a Salesforce activity record.

Only then click the app button to advance the batch.

Daily workflow

Check Outlook for replies and flag them in the app.

Download the due merge CSV.

Run the Word macro.

Advance the batch only when the macro reports zero failures.

Download a state backup after major uploads or changes.
