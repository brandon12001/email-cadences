#!/usr/bin/env python3
"""Streamlit email cadence platform with Anthropic company tailoring."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import pandas as pd
import streamlit as st

for secret_name in (
    "APP_PASSWORD",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_WEB_SEARCH",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASS",
    "SF_BCC",
):
    try:
        if secret_name in st.secrets and st.secrets[secret_name] not in (None, ""):
            os.environ[secret_name] = str(st.secrets[secret_name])
    except Exception:
        pass

import cadence_engine as eng

REQUIRED_ENGINE_API = "anthropic-tailoring-v1"
REQUIRED_ENGINE_FUNCTIONS = (
    "has_tailored_sequence",
    "step_for_contact",
    "tailor_contact_sequence",
    "cache_tailored_sequence",
    "normalise_state",
)

st.set_page_config(page_title="Email Cadences", layout="wide")

missing_engine_functions = [
    name for name in REQUIRED_ENGINE_FUNCTIONS if not hasattr(eng, name)
]
engine_version = getattr(eng, "ENGINE_API_VERSION", "legacy")
if missing_engine_functions or engine_version != REQUIRED_ENGINE_API:
    st.error(
        "Deployment mismatch: app.py and cadence_engine.py are from different "
        "versions. Replace BOTH files in the GitHub repository with the matched "
        "hotfix files, then reboot the Streamlit app."
    )
    st.code(
        f"Engine version: {engine_version}\n"
        f"Missing functions: {', '.join(missing_engine_functions) or 'none'}"
    )
    st.stop()

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SMTP_KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
ANTHROPIC_READY = bool(os.environ.get("ANTHROPIC_API_KEY"))
DEFAULT_WEB_SEARCH = os.environ.get("ANTHROPIC_WEB_SEARCH", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}


def check_password() -> bool:
    required = os.environ.get("APP_PASSWORD", "")
    if not required:
        return True
    if st.session_state.get("auth_ok"):
        return True

    st.title("Email Cadences - sign in")
    password = st.text_input("Password", type="password")
    if st.button("Enter"):
        if password == required:
            st.session_state.auth_ok = True
            st.rerun()
        else:
            st.error("Wrong password.")
    return False


if not check_password():
    st.stop()

if "state" not in st.session_state:
    st.session_state.state = eng.normalise_state(eng.load_state())
    if not st.session_state.state["cadences"]:
        st.session_state.state["cadences"]["default"] = eng.DEFAULT_CADENCE

state = st.session_state.state


def persist() -> None:
    eng.save_state(state)


def contact_label(contact: dict[str, Any]) -> str:
    title = str(contact.get("title") or "").strip()
    suffix = f" | {title}" if title else ""
    return f"{contact.get('name', '')} | {contact.get('company', '')}{suffix}"


def flash_message() -> None:
    flash = st.session_state.pop("flash", None)
    if not flash:
        return
    kind, text = flash
    getattr(st, kind, st.info)(text)


smtp_values = {key: os.environ.get(key, "") for key in SMTP_KEYS}
smtp_ready = all(smtp_values.values())
smtp_partial = any(smtp_values.values()) and not smtp_ready
sender_mode = "SMTP" if smtp_ready else "Word and Outlook macro"
salesforce_status = (
    "SMTP BCC configured"
    if smtp_ready and os.environ.get("SF_BCC")
    else "handled by the Word macro"
)
claude_status = f"configured ({ANTHROPIC_MODEL})" if ANTHROPIC_READY else "NOT configured"

st.title("Email Cadences")
st.caption(
    f"Claude: **{claude_status}**  |  Salesforce: **{salesforce_status}**  |  "
    f"Sender: **{sender_mode}**  |  Contacts: {len(state['contacts'])}"
)
flash_message()

if smtp_partial:
    missing = [key for key, value in smtp_values.items() if not value]
    st.warning(f"SMTP is only partly configured. Missing: {', '.join(missing)}")

if not ANTHROPIC_READY:
    st.warning(
        "Add ANTHROPIC_API_KEY to Streamlit secrets. The app will not export generic "
        "emails while Claude tailoring is unavailable."
    )

tab_send, tab_contacts, tab_cadence, tab_settings = st.tabs(
    ["Send today", "Contacts", "Cadence", "Settings"]
)

with tab_send:
    st.subheader("Daily run")
    st.caption(
        "Claude researches and writes one cached three-email sequence per contact. "
        "Only Claude-tailored contacts can enter the Word merge CSV."
    )

    cadence = state["cadences"]["default"]
    active = [contact for contact in state["contacts"] if contact.get("status") == "active"]
    due = [contact for contact in active if eng.contact_due(contact, cadence)]
    tailored_due = [contact for contact in due if eng.has_tailored_sequence(contact, cadence)]
    untailored_due = [contact for contact in due if not eng.has_tailored_sequence(contact, cadence)]

    metric_1, metric_2, metric_3 = st.columns(3)
    metric_1.metric("Due now", len(due))
    metric_2.metric("Claude-tailored and ready", len(tailored_due))
    metric_3.metric("Awaiting Claude", len(untailored_due))

    st.subheader("1. Tailor the next due contacts")
    st.caption(
        "One Anthropic request generates all three emails for one contact and caches "
        "them in the state file. Only first name, role, company, domain and your supplied "
        "research are sent to Anthropic."
    )

    control_1, control_2, control_3 = st.columns(3)
    tailor_count = control_1.number_input(
        "Contacts this run",
        min_value=1,
        max_value=25,
        value=min(10, max(1, len(untailored_due) or 1)),
        key="tailor_count",
    )
    use_web_search = control_2.checkbox(
        "Research companies on the web",
        value=DEFAULT_WEB_SEARCH,
        help="Allows up to one Anthropic web search per contact.",
    )
    retaylor = control_3.checkbox(
        "Regenerate existing copy",
        value=False,
        help="Include already-tailored due contacts and overwrite their saved sequence.",
    )

    tailoring_candidates = due if retaylor else untailored_due
    tailoring_batch = tailoring_candidates[: int(tailor_count)]
    tailor_disabled = not ANTHROPIC_READY or not tailoring_batch

    if use_web_search:
        st.caption(
            "Web research is the part that makes the copy genuinely company-specific. "
            "Claude is instructed to avoid unsupported claims and to fall back to the "
            "CSV context when research is inconclusive."
        )

    if st.button(
        f"Tailor {len(tailoring_batch)} contact(s) with Claude",
        type="primary",
        disabled=tailor_disabled,
    ):
        progress = st.progress(0.0)
        log_box = st.container()
        completed = 0
        failed = 0
        excluded = 0

        for index, contact in enumerate(tailoring_batch):
            result, error = eng.tailor_contact_sequence(
                contact=contact,
                cadence=cadence,
                api_key=os.environ["ANTHROPIC_API_KEY"],
                model=ANTHROPIC_MODEL,
                use_web_search=use_web_search,
            )

            if error or result is None:
                failed += 1
                contact["tailoring_error"] = error or "Unknown Claude error"
                log_box.write(
                    f"Failed: {contact_label(contact)} | {contact['tailoring_error']}"
                )
            elif result.get("skip"):
                excluded += 1
                contact["status"] = "excluded"
                contact["excluded_reason"] = result.get("skip_reason", "Restricted sector")
                contact["tailoring"] = {
                    "model": result.get("model", ANTHROPIC_MODEL),
                    "web_search": bool(result.get("web_search")),
                    "research_summary": result.get("research_summary", ""),
                    "generated_at": time.strftime("%d/%m/%Y %H:%M"),
                }
                log_box.write(
                    f"Excluded: {contact_label(contact)} | {contact['excluded_reason']}"
                )
            else:
                completed += 1
                eng.cache_tailored_sequence(contact, result)
                source = "web research" if result.get("web_search") else "CSV context"
                log_box.write(f"Tailored: {contact_label(contact)} | {source}")

            progress.progress((index + 1) / len(tailoring_batch))

        persist()
        st.session_state.flash = (
            "success" if failed == 0 else "warning",
            f"Claude tailored {completed}, excluded {excluded}, failed {failed}.",
        )
        st.rerun()

    if not tailoring_batch and ANTHROPIC_READY:
        st.success("Every due contact in the current state already has tailored copy.")

    st.divider()
    st.subheader("2. Review and download the Word merge batch")
    batch_size = st.number_input("Send batch size", 1, 200, 40, key="send_batch_size")
    merge_batch = tailored_due[: int(batch_size)]

    if merge_batch:
        rows = []
        for contact in merge_batch:
            step_index = int(contact.get("step", 0) or 0)
            step_definition = eng.step_for_contact(contact, cadence, step_index)
            subject, body = eng.build_email(
                contact,
                step_definition,
                include_manual_signature=False,
            )
            rows.append(
                {
                    "email": contact["email"],
                    "first_name": eng.first_name(contact.get("name", "")),
                    "name": contact.get("name", ""),
                    "company": contact.get("company", ""),
                    "title": contact.get("title", ""),
                    "step": step_index + 1,
                    "subject": subject,
                    "body": body.replace("\r\n", "\n").replace("\n", "\\n"),
                }
            )

        with st.expander("Review every email in this batch", expanded=True):
            for index, (contact, row) in enumerate(zip(merge_batch, rows), start=1):
                st.markdown(
                    f"**{index}. {contact.get('name', '')} | {contact.get('company', '')} "
                    f"| Step {row['step']}**"
                )
                research = contact.get("tailoring", {}).get("research_summary", "")
                if research:
                    st.caption(f"Claude rationale: {research}")
                st.markdown(f"**Subject:** {row['subject']}")
                st.text(row["body"].replace("\\n", "\n"))
                st.divider()

        merge_frame = pd.DataFrame(rows)
        st.download_button(
            f"Download tailored merge CSV ({len(rows)} emails)",
            merge_frame.to_csv(index=False).encode("utf-8"),
            file_name=f"cadence_merge_{time.strftime('%d-%m-%Y')}.csv",
            mime="text/csv",
            type="primary",
        )

        st.warning(
            "Only click advance after the macro says every email sent successfully. "
            "If it reports any failures, do not advance the batch."
        )
        if st.button(f"I have sent this batch - advance all {len(rows)}"):
            for contact, row in zip(merge_batch, rows):
                eng.advance(contact)
                eng.mark_finished_if_done(contact, cadence)
                state["log"].append(
                    {
                        "t": time.strftime("%d/%m/%Y %H:%M"),
                        "who": contact["email"],
                        "step": contact["step"],
                        "subject": row["subject"],
                        "source": "Claude via Word macro",
                    }
                )
            persist()
            st.session_state.flash = ("success", f"Advanced {len(rows)} contacts.")
            st.rerun()
    elif due:
        st.info("No due contacts are exportable yet. Tailor them with Claude first.")
    else:
        st.info("No active contacts are due right now.")

    if smtp_ready and tailored_due:
        st.divider()
        st.subheader("Optional direct SMTP send")
        st.caption(
            "This is separate from the Word macro. It sends the same Claude-tailored copy "
            "but does not use your formatted Outlook signature."
        )
        daily_cap = st.number_input("Max SMTP sends", 1, 200, 40)
        gap_seconds = st.slider("Seconds between SMTP sends", 5, 60, 15)
        if st.button("Run SMTP send"):
            sent = 0
            failed = 0
            batch = tailored_due[: int(daily_cap)]
            progress = st.progress(0.0)
            log_box = st.container()

            for index, contact in enumerate(batch):
                step_index = int(contact.get("step", 0) or 0)
                step_definition = eng.step_for_contact(contact, cadence, step_index)
                subject, body = eng.build_email(contact, step_definition)
                ok, error = eng.smtp_send(
                    smtp_values["SMTP_HOST"],
                    smtp_values["SMTP_PORT"],
                    smtp_values["SMTP_USER"],
                    smtp_values["SMTP_PASS"],
                    contact["email"],
                    subject,
                    body,
                    os.environ.get("SF_BCC", ""),
                )
                if ok:
                    eng.advance(contact)
                    eng.mark_finished_if_done(contact, cadence)
                    sent += 1
                    log_box.write(f"Sent: {contact_label(contact)}")
                    if index < len(batch) - 1:
                        time.sleep(gap_seconds)
                else:
                    failed += 1
                    log_box.write(f"Failed: {contact_label(contact)} | {error}")
                progress.progress((index + 1) / len(batch))

            persist()
            st.success(f"Done. Sent {sent}, failed {failed}.")

    st.divider()
    st.subheader("Flag replies before the next batch")
    stoppable = [
        contact
        for contact in state["contacts"]
        if contact.get("status") == "active" and int(contact.get("step", 0) or 0) > 0
    ]
    if stoppable:
        reply_labels = [f"{contact_label(contact)} <{contact['email']}>" for contact in stoppable]
        selected_reply = st.selectbox("Contact", reply_labels)
        if st.button("Mark replied and stop sequence"):
            selected_email = selected_reply.rsplit("<", 1)[1].rstrip(">")
            for contact in state["contacts"]:
                if contact.get("email") == selected_email:
                    eng.mark_replied(contact)
                    break
            persist()
            st.rerun()
    else:
        st.caption("No previously emailed active contacts are available to flag.")

with tab_contacts:
    st.subheader("Upload contacts")
    st.caption(
        "Required CSV columns: name, email, company. Optional: title, website and ammo. "
        "The title column from your 1,510-contact CSV is now retained and used by Claude."
    )
    upload = st.file_uploader("CSV", type=["csv"])
    if upload is not None:
        try:
            frame = pd.read_csv(upload, dtype=str).fillna("")
        except Exception as exc:
            st.error(f"Could not read the CSV: {exc}")
        else:
            columns = {str(column).lower().strip(): column for column in frame.columns}
            missing = [key for key in ("name", "email", "company") if key not in columns]
            if missing:
                st.error(f"Missing columns: {missing}")
            else:
                existing_by_email = {
                    str(contact.get("email", "")).lower(): contact
                    for contact in state["contacts"]
                }
                added = 0
                updated = 0
                duplicates = 0
                invalid = 0

                for _, row in frame.iterrows():
                    email = str(row[columns["email"]]).strip().lower()
                    if not EMAIL_RE.match(email):
                        invalid += 1
                        continue

                    def optional_value(column_name: str) -> str:
                        source = columns.get(column_name)
                        return str(row[source]).strip() if source else ""

                    incoming = {
                        "name": str(row[columns["name"]]).strip(),
                        "company": str(row[columns["company"]]).strip(),
                        "title": optional_value("title"),
                        "website": optional_value("website"),
                        "ammo": optional_value("ammo"),
                    }

                    if email in existing_by_email:
                        contact = existing_by_email[email]
                        changed = False
                        for field, value in incoming.items():
                            if value and str(contact.get(field) or "").strip() != value:
                                contact[field] = value
                                changed = True
                        if changed:
                            updated += 1
                        else:
                            duplicates += 1
                        continue

                    contact = {
                        **incoming,
                        "email": email,
                        "status": "active",
                        "step": 0,
                        "last_sent": None,
                    }
                    state["contacts"].append(contact)
                    existing_by_email[email] = contact
                    added += 1

                persist()
                st.success(
                    f"Added {added}, enriched {updated} existing contacts, skipped "
                    f"{duplicates} unchanged duplicates and {invalid} invalid rows."
                )

    st.divider()
    if state["contacts"]:
        contacts_rows = []
        for contact in state["contacts"]:
            contacts_rows.append(
                {
                    **contact,
                    "tailored": eng.has_tailored_sequence(
                        contact, state["cadences"]["default"]
                    ),
                    "research_summary": contact.get("tailoring", {}).get(
                        "research_summary", ""
                    ),
                }
            )
        contacts_frame = pd.DataFrame(contacts_rows)
        filter_column, summary_column = st.columns(2)
        statuses = filter_column.multiselect(
            "Status",
            ["active", "replied", "finished", "excluded"],
            default=["active", "replied"],
        )
        view = (
            contacts_frame[contacts_frame["status"].isin(statuses)]
            if statuses
            else contacts_frame
        )
        summary_column.metric("Shown", len(view))
        display_columns = [
            "name",
            "email",
            "company",
            "title",
            "status",
            "step",
            "tailored",
            "last_sent",
        ]
        st.dataframe(
            view[display_columns],
            use_container_width=True,
            height=420,
        )
        st.download_button(
            "Download contacts CSV",
            contacts_frame.to_csv(index=False).encode("utf-8-sig"),
            "cadence_contacts.csv",
            "text/csv",
        )

with tab_cadence:
    st.subheader("Base strategy")
    st.caption(
        "These templates provide strategic direction to Claude. Claude rewrites all three "
        "steps for each contact. Wait days still control when each cached step becomes due."
    )
    cadence = state["cadences"]["default"]
    for index, step in enumerate(cadence["steps"]):
        with st.expander(
            f"Step {index + 1} - wait {step['wait_days']} days",
            expanded=index == 0,
        ):
            step["wait_days"] = st.number_input(
                "Wait days before this step",
                0,
                30,
                int(step["wait_days"]),
                key=f"wait_{index}",
            )
            step["subject"] = st.text_input(
                "Fallback subject and Claude guidance",
                step["subject"],
                key=f"subject_{index}",
            )
            step["body"] = st.text_area(
                "Fallback body and Claude guidance",
                step["body"],
                height=220,
                key=f"body_{index}",
            )

    if st.button("Save base strategy"):
        persist()
        st.success("Saved. Existing tailored sequences are unchanged until regenerated.")

    st.divider()
    st.subheader("Preview a saved tailored sequence")
    tailored_contacts = [
        contact
        for contact in state["contacts"]
        if eng.has_tailored_sequence(contact, cadence)
    ]
    if tailored_contacts:
        labels = [contact_label(contact) for contact in tailored_contacts[:200]]
        selected = st.selectbox("Contact", labels)
        contact = tailored_contacts[labels.index(selected)]
        research = contact.get("tailoring", {}).get("research_summary", "")
        if research:
            st.info(research)
        for index in range(len(cadence["steps"])):
            step = eng.step_for_contact(contact, cadence, index)
            subject, body = eng.build_email(contact, step)
            with st.expander(f"Step {index + 1}: {subject}", expanded=index == 0):
                st.text(body)
                st.caption("The Outlook signature appears underneath Best,")
    else:
        st.info("No contacts have been tailored yet.")

with tab_settings:
    st.subheader("Anthropic setup")
    st.code(
        'APP_PASSWORD = "your-password"\n'
        'ANTHROPIC_API_KEY = "sk-ant-..."\n'
        f'ANTHROPIC_MODEL = "{ANTHROPIC_MODEL}"\n'
        'ANTHROPIC_WEB_SEARCH = "true"',
        language="toml",
    )
    st.markdown(
        "The API key stays in Streamlit secrets. The app sends only the contact's first "
        "name, role, company, domain and supplied research to Claude. It does not send "
        "the Salesforce BCC or the prospect's full email address."
    )
    st.markdown(
        "Web research can be switched off on the Send today tab. With it off, Claude can "
        "only tailor from the CSV fields and any ammo you supplied."
    )

    st.divider()
    st.subheader("Sending setup")
    st.markdown(
        "**Recommended path:** download the tailored merge CSV and run the Word macro. "
        "The macro applies the Salesforce BCC and preserves your Outlook signature."
    )
    st.markdown(
        "**Optional SMTP path:** set SMTP_HOST, SMTP_PORT, SMTP_USER and SMTP_PASS in "
        "Streamlit secrets. Set SF_BCC as well if Salesforce logging is required."
    )

    st.divider()
    st.subheader("State backup")
    st.caption(
        "Tailored copy is stored inside the state JSON. Streamlit storage can reset after "
        "a redeploy, so download a backup after every meaningful tailoring batch."
    )
    st.download_button(
        "Download state JSON",
        data=json.dumps(state, indent=2, ensure_ascii=False).encode("utf-8"),
        file_name="cadence_state.json",
        mime="application/json",
    )
    restore_upload = st.file_uploader(
        "Restore state JSON", type=["json"], key="restore"
    )
    if restore_upload is not None and st.button("Restore now"):
        try:
            restored = json.loads(restore_upload.read().decode("utf-8"))
            restored = eng.normalise_state(restored)
            if "default" not in restored["cadences"]:
                restored["cadences"]["default"] = eng.DEFAULT_CADENCE
        except Exception as exc:
            st.error(f"Could not restore that state file: {exc}")
        else:
            st.session_state.state = restored
            eng.save_state(restored)
            st.success("Restored.")
            st.rerun()
