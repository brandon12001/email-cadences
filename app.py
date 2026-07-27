#!/usr/bin/env python3
"""
Email Cadence Platform - Streamlit app.

Tabs:
  1. Send today   - the daily button: checks replies, sends due steps
  2. Contacts     - upload CSV, assign to cadence, see pipeline state
  3. Cadence      - edit the sequence (subjects, bodies, wait days)
  4. Settings     - connect mailbox (Graph device-code or SMTP), state backup

Secrets (optional): APP_PASSWORD, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
"""
import io
import os
import time
import pandas as pd
import streamlit as st

for _k in ("APP_PASSWORD", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SF_BCC"):
    try:
        if _k in st.secrets and st.secrets[_k]:
            os.environ[_k] = str(st.secrets[_k])
    except Exception:
        pass

import cadence_engine as eng

st.set_page_config(page_title="Email Cadences", layout="wide")

# ---- password gate ----
def check_password():
    required = os.environ.get("APP_PASSWORD", "")
    if not required:
        return True
    if st.session_state.get("auth_ok"):
        return True
    st.title("Email Cadences — sign in")
    pw = st.text_input("Password", type="password")
    if st.button("Enter"):
        if pw == required:
            st.session_state.auth_ok = True
            st.rerun()
        else:
            st.error("Wrong password.")
    return False

if not check_password():
    st.stop()

# ---- state ----
if "state" not in st.session_state:
    st.session_state.state = eng.load_state()
    if not st.session_state.state["cadences"]:
        st.session_state.state["cadences"]["default"] = eng.DEFAULT_CADENCE
state = st.session_state.state

def persist():
    eng.save_state(state)

st.title("Email Cadences")
mode = "SMTP" if os.environ.get("SMTP_USER") else "Draft mode (copy-paste to Outlook)"
sf = "on" if os.environ.get("SF_BCC") else "OFF - set SF_BCC secret"
st.caption(f"Salesforce BCC: **{sf}**  ·  Sender: **{mode}**  ·  Contacts: {len(state['contacts'])}  ·  "
           f"Cadence steps: {len(state['cadences']['default']['steps'])}")

tab_send, tab_contacts, tab_cadence, tab_settings = st.tabs(
    ["📤 Send today", "👥 Contacts", "✏️ Cadence", "⚙️ Settings"])

# ===========================================================================
# TAB: Send today
# ===========================================================================
with tab_send:
    st.subheader("Daily run")
    st.caption("One button. Checks for replies first (Graph mode), then sends "
               "every due step with a human-speed gap. Anyone who replied is "
               "stopped automatically.")

    cadence = state["cadences"]["default"]
    active = [c for c in state["contacts"] if c.get("status") == "active"]
    due = [c for c in active if eng.contact_due(c, cadence)]
    st.metric("Due to send now", len(due))

    # ---- Word mail-merge workflow ----
    st.subheader("Daily merge CSV (for Word)")
    st.caption("Download today's due emails fully written, one row each, run your "
               "Word mail merge from it, then confirm the batch below so the app "
               "advances everyone to their next step.")
    cap_merge = st.number_input("Batch size", 1, 200, 40, key="cap_merge")
    batch_m = due[: int(cap_merge)]
    if batch_m:
        rows = []
        for c in batch_m:
            sd = cadence["steps"][c.get("step", 0)]
            subj, body = eng.build_email(c, sd)
            rows.append({"email": c["email"], "first_name": eng.first_name(c.get("name","")),
                         "name": c.get("name",""), "company": c.get("company",""),
                         "step": c.get("step", 0) + 1, "subject": subj, "body": body})
        dfm = pd.DataFrame(rows)
        st.download_button(
            f"Download merge CSV ({len(rows)} emails)",
            dfm.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"cadence_merge_{time.strftime('%d-%m-%Y')}.csv",
            mime="text/csv", type="primary")
        with st.expander("Preview first 3 rows"):
            for r in rows[:3]:
                st.markdown(f"**{r['email']}** — step {r['step']} — {r['subject']}")
                st.text(r["body"][:400])
        if st.button(f"I've sent this batch — advance all {len(rows)}"):
            for c in batch_m:
                eng.advance(c)
                eng.mark_finished_if_done(c, cadence)
                state["log"].append({"t": time.strftime("%d/%m/%Y %H:%M"),
                                     "who": c["email"], "step": c["step"],
                                     "subject": "via Word merge"})
            persist()
            st.success(f"Advanced {len(rows)} contacts.")
            st.rerun()
    st.divider()

    daily_cap = st.number_input("Max sends this run", 1, 200, 40)
    gap_secs = st.slider("Seconds between sends", 5, 60, 15)

    st.warning("Before you run: flag anyone who has replied (control below) so they are not sent the next step.")
    if st.button("Run: send due steps", type="primary", disabled=not due):
        sent = failed = 0
        prog = st.progress(0.0)
        logbox = st.container()
        batch = due[: int(daily_cap)]
        for i, c in enumerate(batch):
            step_def = cadence["steps"][c.get("step", 0)]
            subject, body = eng.build_email(c, step_def)
            ok, err = False, "no sender connected"
            if os.environ.get("SMTP_USER"):
                ok, err = eng.smtp_send(os.environ["SMTP_HOST"],
                                        os.environ.get("SMTP_PORT", "587"),
                                        os.environ["SMTP_USER"],
                                        os.environ["SMTP_PASS"],
                                        c["email"], subject, body,
                                        os.environ.get("SF_BCC", ""))
            if ok:
                eng.advance(c)
                eng.mark_finished_if_done(c, cadence)
                state["log"].append({"t": time.strftime("%d/%m/%Y %H:%M"),
                                     "who": c["email"], "step": c["step"],
                                     "subject": subject})
                sent += 1
                logbox.write(f"✅ step {c['step']} → {c['name']} ({c['company']})")
                time.sleep(gap_secs)
            else:
                failed += 1
                logbox.write(f"❌ {c['name']}: {err}")
            prog.progress((i + 1) / len(batch))
        persist()
        st.success(f"Done. Sent {sent}, {failed} failed.")

    if not os.environ.get("SMTP_USER"):
        st.info("No sender connected — you're in **draft mode**. Below are today's "
                "due emails ready to copy into Outlook.")
        for c in due[:20]:
            step_def = state["cadences"]["default"]["steps"][c.get("step", 0)]
            subject, body = eng.build_email(c, step_def)
            with st.expander(f"{c['name']} — {c['company']} — step {c.get('step',0)+1}"):
                st.text_input("To", c["email"], key=f"to_{c['email']}")
                st.text_input("Subject", subject, key=f"su_{c['email']}")
                st.text_area("Body", body, height=260, key=f"bo_{c['email']}")
                if st.button("Mark as sent", key=f"ms_{c['email']}"):
                    eng.advance(c)
                    eng.mark_finished_if_done(c, state["cadences"]["default"])
                    persist(); st.rerun()

    st.divider()
    st.subheader("Flag replies (do this before each run)")
    st.caption("Anyone who replied in your inbox: flag them here and the sequence stops for good.")
    stoppable = [c for c in state["contacts"] if c.get("status") == "active" and c.get("step", 0) > 0]
    if stoppable:
        pick = st.selectbox("Contact", [f"{c['name']} <{c['email']}>" for c in stoppable])
        if st.button("Mark replied / stop sequence"):
            email = pick.split("<")[1].rstrip(">")
            for c in state["contacts"]:
                if c["email"] == email:
                    eng.mark_replied(c)
            persist(); st.rerun()

# ===========================================================================
# TAB: Contacts
# ===========================================================================
with tab_contacts:
    st.subheader("Upload contacts")
    st.caption("CSV needs: name, email, company. Optional: ammo (a fact line "
               "from the CH call sheet that opens email 1).")
    up = st.file_uploader("CSV", type=["csv"])
    if up is not None:
        df = pd.read_csv(up, dtype=str).fillna("")
        cols = {c.lower().strip(): c for c in df.columns}
        needed = [k for k in ("name", "email", "company") if k not in cols]
        if needed:
            st.error(f"Missing columns: {needed}")
        else:
            existing = {c["email"].lower() for c in state["contacts"]}
            added = skipped = 0
            for _, r in df.iterrows():
                email = str(r[cols["email"]]).strip().lower()
                if not email or email in existing:
                    skipped += 1
                    continue
                state["contacts"].append({
                    "name": str(r[cols["name"]]).strip(),
                    "email": email,
                    "company": str(r[cols["company"]]).strip(),
                    "ammo": str(r[cols.get("ammo", "")]).strip() if cols.get("ammo") else "",
                    "status": "active", "step": 0, "last_sent": None,
                })
                existing.add(email)
                added += 1
            persist()
            st.success(f"Added {added}, skipped {skipped} (duplicates/blank).")

    st.divider()
    if state["contacts"]:
        dfc = pd.DataFrame(state["contacts"])
        f1, f2 = st.columns(2)
        statuses = f1.multiselect("Status", ["active", "replied", "finished"],
                                  default=["active", "replied"])
        view = dfc[dfc["status"].isin(statuses)] if statuses else dfc
        st.dataframe(view[["name", "email", "company", "status", "step", "last_sent"]],
                     use_container_width=True, height=380)
        st.download_button("Download contacts CSV",
                           dfc.to_csv(index=False).encode("utf-8-sig"),
                           "cadence_contacts.csv", "text/csv")

# ===========================================================================
# TAB: Cadence editor
# ===========================================================================
with tab_cadence:
    st.subheader("Sequence")
    st.caption("Merge fields: {first_name} {company} {ammo_line}. The regulatory "
               "footer and opt-out line are appended automatically to every email.")
    cadence = state["cadences"]["default"]
    for i, step in enumerate(cadence["steps"]):
        with st.expander(f"Step {i+1} — wait {step['wait_days']} days", expanded=(i == 0)):
            step["wait_days"] = st.number_input("Wait days before this step", 0, 30,
                                                step["wait_days"], key=f"w{i}")
            step["subject"] = st.text_input("Subject", step["subject"], key=f"s{i}")
            step["body"] = st.text_area("Body", step["body"], height=260, key=f"b{i}")
    c1, c2 = st.columns(2)
    if c1.button("Save cadence"):
        persist(); st.success("Saved.")
    if c2.button("Add a step"):
        cadence["steps"].append({"wait_days": 4, "subject": "Re: Currency planning at {company}",
                                 "body": "{first_name},\n\n...\n\nBest,\nBrandon Ellis\nLumon"})
        persist(); st.rerun()

    st.divider()
    st.subheader("Preview with a real contact")
    if state["contacts"]:
        pick = st.selectbox("Preview as", [f"{c['name']} — {c['company']}" for c in state["contacts"][:50]])
        idx = [f"{c['name']} — {c['company']}" for c in state["contacts"][:50]].index(pick)
        c = state["contacts"][idx]
        for i, stp in enumerate(cadence["steps"]):
            subj, body = eng.build_email(c, stp)
            with st.expander(f"Step {i+1}: {subj}"):
                st.text(body)

# ===========================================================================
# TAB: Settings
# ===========================================================================
with tab_settings:
    st.subheader("Sending setup")
    st.markdown("---")
    st.markdown("**SMTP (recommended):** set SMTP_HOST/PORT/USER/PASS in "
                "Streamlit secrets (e.g. smtp.office365.com, 587, your address, "
                "an app password). Replies land in your Outlook as normal; flag them on the Send tab before each run. Leave SMTP unset to use draft mode (copy-paste).")

    st.markdown("---")
    st.subheader("State backup")
    st.caption("Streamlit free tier can reset storage on redeploys. Download the "
               "state after big changes; upload to restore.")
    stbytes = io.BytesIO(pd.io.json.dumps(state).encode() if hasattr(pd.io, 'json') else b"")
    st.download_button("Download state (JSON)",
                       data=bytes(__import__('json').dumps(state, indent=2), 'utf-8'),
                       file_name="cadence_state.json", mime="application/json")
    upst = st.file_uploader("Restore state (JSON)", type=["json"], key="restore")
    if upst is not None and st.button("Restore now"):
        import json as _json
        st.session_state.state = _json.loads(upst.read().decode("utf-8"))
        eng.save_state(st.session_state.state)
        st.success("Restored."); st.rerun()
