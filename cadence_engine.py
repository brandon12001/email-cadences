#!/usr/bin/env python3
"""
Cadence engine - sequencing, reply detection, sending.

Design:
- Contacts move through a cadence: step 0 -> wait -> step 1 -> wait -> step 2.
- A send is only made when due AND no reply has been detected from the contact.
- Reply detection checks the connected mailbox for any message FROM the
  contact's email address received after their first send.
- State lives in a single JSON file (cadence_state.json) so the app works on
  Streamlit Cloud without a database. Download/upload state for backup.

Senders supported:
  1. SMTP (e.g. smtp.office365.com with an app password): sends from your
     address. Replies land in Outlook; flag them in the app before each run.
  2. Draft mode: no sending - generates ready-to-paste emails.
"""
import json
import re
import time
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import requests

STATE_FILE = Path("cadence_state.json")

REG_FOOTER = (
    "\n\nIf you would rather not hear from me again, reply with 'no thanks' and I will close your file."
)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"cadences": {}, "contacts": [], "log": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Templating
# ---------------------------------------------------------------------------
def render(template: str, contact: dict) -> str:
    out = template
    for key, val in contact.items():
        out = out.replace("{" + key + "}", str(val or ""))
    # strip any unresolved merge fields cleanly
    out = re.sub(r"\{[a-z_]+\}", "", out)
    return out


def first_name(full: str) -> str:
    return (full or "").strip().split(" ")[0].title()


# ---------------------------------------------------------------------------
# Cadence logic
# ---------------------------------------------------------------------------
def contact_due(contact: dict, cadence: dict, now=None) -> bool:
    """Is this contact due their next step?"""
    if contact.get("status") not in ("active",):
        return False
    step = contact.get("step", 0)
    steps = cadence.get("steps", [])
    if step >= len(steps):
        return False
    if step == 0:
        return True  # first email due immediately on assignment
    last = contact.get("last_sent")
    if not last:
        return True
    wait_days = steps[step].get("wait_days", 3)
    due_at = datetime.fromisoformat(last) + timedelta(days=wait_days)
    return (now or datetime.now(timezone.utc)) >= due_at


def advance(contact: dict):
    contact["step"] = contact.get("step", 0) + 1
    contact["last_sent"] = datetime.now(timezone.utc).isoformat()


def mark_replied(contact: dict):
    contact["status"] = "replied"
    contact["replied_at"] = datetime.now(timezone.utc).isoformat()


def mark_finished_if_done(contact: dict, cadence: dict):
    if contact.get("step", 0) >= len(cadence.get("steps", [])):
        contact["status"] = "finished"


# ---------------------------------------------------------------------------
# SMTP fallback (send-only)
# ---------------------------------------------------------------------------
def smtp_send(host, port, user, password, to_addr, subject, body, bcc_addr=""):
    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = subject
    if bcc_addr:
        msg["Bcc"] = bcc_addr
    msg.attach(MIMEText(body, "plain"))
    try:
        recipients = [to_addr] + ([bcc_addr] if bcc_addr else [])
        with smtplib.SMTP(host, int(port), timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(user, recipients, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)[:200]


# ---------------------------------------------------------------------------
# Default cadence - strategy-led, per the operating rules
# ---------------------------------------------------------------------------
DEFAULT_CADENCE = {
    "name": "FX intro - strategy led",
    "steps": [
        {
            "wait_days": 0,
            "subject": "Currency planning at {company}",
            "body": (
                "{first_name},\n\n"
                "{ammo_line}"
                "Moves in exchange rates can erode margins, and for a business "
                "buying or selling overseas that risk sits on every transaction.\n\n"
                "That is what we help companies manage at Lumon: locking rates ahead "
                "for your purchasing or sales cycle so costs are known when you commit, "
                "not when the invoice lands.\n\n"
                "Worth a short conversation on how that would work for {company}?\n\n"
                "Best,\nBrandon Ellis\nLumon"
            ),
        },
        {
            "wait_days": 3,
            "subject": "Re: Currency planning at {company}",
            "body": (
                "{first_name},\n\n"
                "Following up on my note earlier this week. The reason I think this is "
                "worth ten minutes: most businesses only look at currency when a rate "
                "move has already cost them. Planning it in advance is what keeps "
                "margins predictable.\n\n"
                "If there is someone better placed on this at {company}, happy to be "
                "pointed their way.\n\n"
                "Best,\nBrandon Ellis\nLumon"
            ),
        },
        {
            "wait_days": 4,
            "subject": "Re: Currency planning at {company}",
            "body": (
                "{first_name},\n\n"
                "Last note from me. If currency planning is not a priority right now, "
                "no problem at all - I will leave it here.\n\n"
                "If it becomes one, a named day works best: I hold Tuesday and Thursday "
                "mornings for these conversations, and a ten-minute call is usually "
                "enough to see whether there is anything in it for {company}.\n\n"
                "Best,\nBrandon Ellis\nLumon"
            ),
        },
    ],
}


def build_email(contact: dict, step_def: dict):
    c = dict(contact)
    c["first_name"] = first_name(contact.get("name", ""))
    ammo = (contact.get("ammo") or "").strip()
    c["ammo_line"] = (ammo + "\n\n") if ammo else ""
    subject = render(step_def["subject"], c)
    body = render(step_def["body"], c) + REG_FOOTER
    return subject, body
