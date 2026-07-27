#!/usr/bin/env python3
"""Cadence sequencing and email rendering helpers."""

import json
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

STATE_FILE = Path("cadence_state.json")

OPT_OUT_FOOTER = (
    "\n\nIf you would rather not hear from me again, reply with 'no thanks' "
    "and I will close your file."
)

SIGN_OFF = "\n\nBest,"
LEGACY_SIGNATURE_SUFFIXES = (
    "\n\nBest,\nBrandon Ellis\nLumon",
    "\nBest,\nBrandon Ellis\nLumon",
)


def _default_state() -> dict:
    return {"cadences": {}, "contacts": [], "log": []}


def normalise_state(state: object) -> dict:
    """Return a usable state dictionary and migrate legacy template sign-offs."""
    if not isinstance(state, dict):
        state = _default_state()

    state.setdefault("cadences", {})
    state.setdefault("contacts", [])
    state.setdefault("log", [])

    if not isinstance(state["cadences"], dict):
        state["cadences"] = {}
    if not isinstance(state["contacts"], list):
        state["contacts"] = []
    if not isinstance(state["log"], list):
        state["log"] = []

    for cadence in state["cadences"].values():
        if not isinstance(cadence, dict):
            continue
        for step in cadence.get("steps", []):
            if not isinstance(step, dict):
                continue
            body = str(step.get("body", ""))
            for suffix in LEGACY_SIGNATURE_SUFFIXES:
                if body.endswith(suffix):
                    body = body[: -len(suffix)].rstrip() + SIGN_OFF
                    break
            step["body"] = body

    return state


def load_state() -> dict:
    if not STATE_FILE.exists():
        return _default_state()
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_state()
    return normalise_state(raw)


def save_state(state: dict) -> None:
    state = normalise_state(state)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def render(template: str, contact: dict) -> str:
    out = str(template or "")
    for key, value in contact.items():
        out = out.replace("{" + key + "}", str(value or ""))
    return re.sub(r"\{[a-z_]+\}", "", out)


def first_name(full_name: str) -> str:
    parts = str(full_name or "").strip().split()
    return parts[0] if parts else ""


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def contact_due(contact: dict, cadence: dict, now: datetime | None = None) -> bool:
    """Return True when an active contact is due their next cadence step."""
    if contact.get("status") != "active":
        return False

    step = int(contact.get("step", 0) or 0)
    steps = cadence.get("steps", [])
    if step < 0 or step >= len(steps):
        return False
    if step == 0:
        return True

    last_sent = _parse_timestamp(contact.get("last_sent"))
    if last_sent is None:
        return True

    wait_days = int(steps[step].get("wait_days", 3) or 0)
    due_at = last_sent + timedelta(days=wait_days)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current >= due_at


def advance(contact: dict) -> None:
    contact["step"] = int(contact.get("step", 0) or 0) + 1
    contact["last_sent"] = datetime.now(timezone.utc).isoformat()


def mark_replied(contact: dict) -> None:
    contact["status"] = "replied"
    contact["replied_at"] = datetime.now(timezone.utc).isoformat()


def mark_finished_if_done(contact: dict, cadence: dict) -> None:
    if int(contact.get("step", 0) or 0) >= len(cadence.get("steps", [])):
        contact["status"] = "finished"


def smtp_send(
    host: str,
    port: str | int,
    user: str,
    password: str,
    to_addr: str,
    subject: str,
    body: str,
    bcc_addr: str = "",
) -> tuple[bool, str]:
    """Send a plain-text email. The BCC is envelope-only and is not exposed."""
    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    recipients = [to_addr] + ([bcc_addr] if bcc_addr else [])
    try:
        with smtplib.SMTP(host, int(port), timeout=30) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.sendmail(user, recipients, msg.as_string())
        return True, ""
    except Exception as exc:
        return False, str(exc)[:200]


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
                "Worth a short conversation on how that would work for {company}?"
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
                "pointed their way."
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
                "enough to see whether there is anything in it for {company}."
            ),
        },
    ],
}


def build_email(
    contact: dict,
    step_def: dict,
    include_manual_signature: bool = False,
) -> tuple[str, str]:
    context = dict(contact)
    context["first_name"] = first_name(contact.get("name", ""))
    ammo = str(contact.get("ammo") or "").strip()
    context["ammo_line"] = (ammo + "\n\n") if ammo else ""

    subject = render(step_def.get("subject", ""), context).strip()
    body = render(step_def.get("body", ""), context).rstrip()

    # Remove any old hard-coded signature so Outlook supplies the real one.
    for suffix in LEGACY_SIGNATURE_SUFFIXES:
        if body.endswith(suffix):
            body = body[: -len(suffix)].rstrip()
            break
    if body.endswith(SIGN_OFF):
        body = body[: -len(SIGN_OFF)].rstrip()

    # The opt-out belongs above the sign-off. The exported message ends at
    # "Best," and the Word macro inserts the Outlook signature underneath.
    body += OPT_OUT_FOOTER + SIGN_OFF
    return subject, body
