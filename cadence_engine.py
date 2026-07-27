#!/usr/bin/env python3
"""Cadence sequencing, Anthropic tailoring, and email rendering helpers."""

from __future__ import annotations

import json
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

STATE_FILE = Path("cadence_state.json")
ENGINE_API_VERSION = "anthropic-tailoring-v1"

OPT_OUT_FOOTER = (
    "\n\nIf you would rather not hear from me again, reply with 'no thanks' "
    "and I will close your file."
)
SIGN_OFF = "\n\nBest,"
LEGACY_SIGNATURE_SUFFIXES = (
    "\n\nBest,\nBrandon Ellis\nLumon",
    "\nBest,\nBrandon Ellis\nLumon",
)
RESTRICTED_SECTORS = ("firearms", "cannabis", "adult", "radioactive")
FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "icloud.com",
    "yahoo.com",
    "yahoo.co.uk",
    "aol.com",
    "proton.me",
    "protonmail.com",
}


def _default_state() -> dict[str, Any]:
    return {"cadences": {}, "contacts": [], "log": []}


def normalise_state(state: object) -> dict[str, Any]:
    """Return a usable state dictionary and migrate legacy contact/template data."""
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
                    body = body[: -len(suffix)].rstrip()
                    break
            if body.endswith(SIGN_OFF):
                body = body[: -len(SIGN_OFF)].rstrip()
            step["body"] = body

    cleaned_contacts: list[dict[str, Any]] = []
    for raw_contact in state["contacts"]:
        if not isinstance(raw_contact, dict):
            continue
        contact = raw_contact
        contact.setdefault("name", "")
        contact.setdefault("email", "")
        contact.setdefault("company", "")
        contact.setdefault("title", "")
        contact.setdefault("website", "")
        contact.setdefault("ammo", "")
        contact.setdefault("status", "active")
        contact.setdefault("step", 0)
        contact.setdefault("last_sent", None)
        cleaned_contacts.append(contact)
    state["contacts"] = cleaned_contacts

    return state


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return _default_state()
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_state()
    return normalise_state(raw)


def save_state(state: dict[str, Any]) -> None:
    state = normalise_state(state)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def render(template: str, contact: dict[str, Any]) -> str:
    out = str(template or "")
    for key, value in contact.items():
        out = out.replace("{" + key + "}", str(value or ""))
    return re.sub(r"\{[a-z_]+\}", "", out)


def first_name(full_name: str) -> str:
    parts = str(full_name or "").strip().split()
    return parts[0] if parts else ""


def company_domain(contact: dict[str, Any]) -> str:
    website = str(contact.get("website") or "").strip()
    if website:
        website = re.sub(r"^https?://", "", website, flags=re.I)
        return website.split("/", 1)[0].lower()

    email = str(contact.get("email") or "").strip().lower()
    if "@" not in email:
        return ""
    domain = email.rsplit("@", 1)[1]
    return "" if domain in FREE_EMAIL_DOMAINS else domain


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


def contact_due(
    contact: dict[str, Any],
    cadence: dict[str, Any],
    now: datetime | None = None,
) -> bool:
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


def advance(contact: dict[str, Any]) -> None:
    contact["step"] = int(contact.get("step", 0) or 0) + 1
    contact["last_sent"] = datetime.now(timezone.utc).isoformat()


def mark_replied(contact: dict[str, Any]) -> None:
    contact["status"] = "replied"
    contact["replied_at"] = datetime.now(timezone.utc).isoformat()


def mark_finished_if_done(contact: dict[str, Any], cadence: dict[str, Any]) -> None:
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
    "name": "FX intro - Claude tailored",
    "steps": [
        {
            "wait_days": 0,
            "subject": "Currency planning at {company}",
            "body": (
                "{first_name},\n\n"
                "{ammo_line}"
                "I wanted to contact you because the way {company} operates may create "
                "currency exposure around overseas purchasing, sales or supplier payments.\n\n"
                "We help businesses compare what they are doing today and put a clearer "
                "plan around rates, timing and margin certainty.\n\n"
                "Worth a ten-minute conversation?"
            ),
        },
        {
            "wait_days": 3,
            "subject": "Re: Currency planning at {company}",
            "body": (
                "{first_name},\n\n"
                "A quick follow-up in case currency sits elsewhere in the business. "
                "The useful starting point is normally a comparison against the current "
                "approach, rather than changing anything for the sake of it.\n\n"
                "Are you the right person for that at {company}?"
            ),
        },
        {
            "wait_days": 4,
            "subject": "Re: Currency planning at {company}",
            "body": (
                "{first_name},\n\n"
                "I will leave it here after this. If reviewing currency costs or planning "
                "becomes relevant, would Tuesday or Thursday suit for a brief comparison?"
            ),
        },
    ],
}


def _clean_generated_text(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_generated_ending(body: str) -> str:
    body = _clean_generated_text(body)
    lower = body.lower()
    opt_out_start = lower.find("if you would rather not hear from me again")
    if opt_out_start >= 0:
        body = body[:opt_out_start].rstrip()

    for suffix in (
        "\n\nBest,\nBrandon Ellis\nLumon",
        "\nBest,\nBrandon Ellis\nLumon",
        "\n\nBest,",
        "\nBest,",
        "Best,",
    ):
        if body.endswith(suffix):
            body = body[: -len(suffix)].rstrip()
            break
    return body


def has_tailored_sequence(contact: dict[str, Any], cadence: dict[str, Any]) -> bool:
    steps = contact.get("tailored_steps")
    expected = len(cadence.get("steps", []))
    if not isinstance(steps, list) or len(steps) != expected:
        return False
    return all(
        isinstance(step, dict)
        and bool(str(step.get("subject") or "").strip())
        and bool(str(step.get("body") or "").strip())
        for step in steps
    )


def step_for_contact(
    contact: dict[str, Any],
    cadence: dict[str, Any],
    step_index: int,
) -> dict[str, Any]:
    if has_tailored_sequence(contact, cadence):
        return contact["tailored_steps"][step_index]
    return cadence["steps"][step_index]


def _extract_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", "") == "text":
            parts.append(str(getattr(block, "text", "")))
    return "\n".join(part for part in parts if part).strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Claude did not return a JSON object")
    parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Claude response was not a JSON object")
    return parsed


def _tailoring_prompt(contact: dict[str, Any], cadence: dict[str, Any]) -> str:
    base_steps = [
        {
            "step": index + 1,
            "wait_days": int(step.get("wait_days", 0) or 0),
            "strategic_intent": _clean_generated_text(step.get("body", "")),
        }
        for index, step in enumerate(cadence.get("steps", []))
    ]
    context = {
        "first_name": first_name(contact.get("name", "")),
        "job_title": str(contact.get("title") or "").strip(),
        "company": str(contact.get("company") or "").strip(),
        "company_domain": company_domain(contact),
        "provided_research": str(contact.get("ammo") or "").strip(),
        "cadence": base_steps,
    }

    return f"""
Create a three-email B2B FX outreach cadence for this specific contact.

CONTACT CONTEXT
{json.dumps(context, ensure_ascii=False, indent=2)}

RESEARCH AND ACCURACY RULES
1. Use the public web search tool to understand the company when available.
2. Only use facts supported by the supplied context or credible public search results.
3. Never invent currencies, FX volumes, countries, suppliers, customers, margins, bank providers, hedging policies, facilities, financial figures or transaction dates.
4. If company research is inconclusive, personalise by the recipient's role and the company's clearly established business model. Do not pretend to know more than you do.
5. Never say that you read filed accounts unless provided_research explicitly contains an accounts fact.
6. Do not promise credit, facilities, pricing or savings.
7. Do not disqualify a company for being small.
8. If the company is clearly in firearms, cannabis, adult services/content or radioactive materials, set skip to true and do not draft emails.

WRITING RULES
1. Write in Brandon's direct, simple British sales style.
2. Use "Lumon", never "Lumon Pay".
3. No em dashes. No hype. No fake familiarity. No generic compliments.
4. Each email must contain a real company-specific reason for contact where research supports one.
5. For finance leaders, focus on control, comparison and margin certainty. For MDs/CEOs, focus on commercial predictability and operational impact.
6. Do not frame forwards as the only answer. Keep the language strategy-led and product-neutral.
7. Email 1: 65 to 105 words. Establish relevance and ask for a ten-minute conversation.
8. Email 2: 45 to 80 words. Use a fresh angle, not a generic "just following up" message.
9. Email 3: 30 to 65 words. Close the loop and use a firm named-day question such as Tuesday or Thursday.
10. Start every body with the recipient's first name followed by a comma.
11. Do not include an opt-out line, "Best,", Brandon's name, Lumon signature text or regulatory footer. The app adds those later.
12. Keep subjects natural and under 65 characters. Follow-up subjects may use "Re:".

Return JSON only in exactly this shape:
{{
  "skip": false,
  "skip_reason": "",
  "research_summary": "One short sentence explaining the strongest verified reason for contact, or that research was inconclusive.",
  "steps": [
    {{"subject": "...", "body": "..."}},
    {{"subject": "...", "body": "..."}},
    {{"subject": "...", "body": "..."}}
  ]
}}
""".strip()


def _call_anthropic(
    api_key: str,
    model: str,
    prompt: str,
    use_web_search: bool,
) -> tuple[Any, bool]:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tools = (
        [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]
        if use_web_search
        else None
    )

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": 1800,
        "temperature": 0.2,
        "system": (
            "You write accurate, restrained UK B2B foreign-exchange sales emails. "
            "You must follow the requested JSON format and never invent company facts."
        ),
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools

    try:
        response = client.messages.create(**kwargs)
        web_enabled = bool(tools)
    except Exception as exc:
        message = str(exc).lower()
        unsupported_tool = bool(tools) and any(
            marker in message
            for marker in ("web_search", "tool", "unsupported", "not available")
        )
        if not unsupported_tool:
            raise
        kwargs.pop("tools", None)
        response = client.messages.create(**kwargs)
        web_enabled = False

    for _ in range(3):
        if getattr(response, "stop_reason", None) != "pause_turn":
            break
        messages.append({"role": "assistant", "content": response.content})
        kwargs["messages"] = messages
        response = client.messages.create(**kwargs)

    return response, web_enabled


def tailor_contact_sequence(
    contact: dict[str, Any],
    cadence: dict[str, Any],
    api_key: str,
    model: str = "claude-haiku-4-5",
    use_web_search: bool = True,
) -> tuple[dict[str, Any] | None, str]:
    """Generate and validate one cached cadence for a contact."""
    if not api_key:
        return None, "ANTHROPIC_API_KEY is not configured"
    if not str(contact.get("company") or "").strip():
        return None, "Company is blank"

    prompt = _tailoring_prompt(contact, cadence)
    try:
        response, web_enabled = _call_anthropic(
            api_key=api_key,
            model=model,
            prompt=prompt,
            use_web_search=use_web_search,
        )
        if getattr(response, "stop_reason", None) == "refusal":
            return None, "Claude refused the tailoring request"
        if getattr(response, "stop_reason", None) == "max_tokens":
            return None, "Claude response was truncated"

        payload = _parse_json_object(_extract_text(response))
    except Exception as exc:
        return None, str(exc)[:300]

    skip = bool(payload.get("skip", False))
    skip_reason = _clean_generated_text(payload.get("skip_reason", ""))[:300]
    research_summary = _clean_generated_text(payload.get("research_summary", ""))[:500]

    if skip:
        return {
            "skip": True,
            "skip_reason": skip_reason or "Claude identified a restricted sector",
            "research_summary": research_summary,
            "steps": [],
            "model": model,
            "web_search": web_enabled,
        }, ""

    raw_steps = payload.get("steps")
    expected_count = len(cadence.get("steps", []))
    if not isinstance(raw_steps, list) or len(raw_steps) != expected_count:
        return None, f"Claude returned {len(raw_steps) if isinstance(raw_steps, list) else 0} steps; expected {expected_count}"

    cleaned_steps: list[dict[str, str]] = []
    recipient_first_name = first_name(contact.get("name", ""))
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            return None, f"Step {index + 1} was not an object"
        subject = _clean_generated_text(raw_step.get("subject", ""))
        body = _strip_generated_ending(str(raw_step.get("body", "")))
        if not subject or not body:
            return None, f"Step {index + 1} was missing a subject or body"
        if len(subject) > 90:
            subject = subject[:90].rstrip()
        if recipient_first_name and not body.lower().startswith(recipient_first_name.lower() + ","):
            body = f"{recipient_first_name},\n\n{body}"
        cleaned_steps.append({"subject": subject, "body": body})

    return {
        "skip": False,
        "skip_reason": "",
        "research_summary": research_summary,
        "steps": cleaned_steps,
        "model": model,
        "web_search": web_enabled,
    }, ""


def cache_tailored_sequence(
    contact: dict[str, Any],
    result: dict[str, Any],
) -> None:
    contact["tailored_steps"] = result.get("steps", [])
    contact["tailoring"] = {
        "model": result.get("model", ""),
        "web_search": bool(result.get("web_search", False)),
        "research_summary": result.get("research_summary", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    contact.pop("tailoring_error", None)


def build_email(
    contact: dict[str, Any],
    step_def: dict[str, Any],
    include_manual_signature: bool = False,
) -> tuple[str, str]:
    del include_manual_signature  # Outlook supplies the real signature in the macro path.

    context = dict(contact)
    context["first_name"] = first_name(contact.get("name", ""))
    ammo = str(contact.get("ammo") or "").strip()
    context["ammo_line"] = (ammo + "\n\n") if ammo else ""

    subject = render(step_def.get("subject", ""), context).strip()
    body = render(step_def.get("body", ""), context).rstrip()
    body = _strip_generated_ending(body)

    # The app adds the opt-out above "Best,". The Word macro then inserts the
    # user's real Outlook signature directly underneath.
    body += OPT_OUT_FOOTER + SIGN_OFF
    return subject, body
