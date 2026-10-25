"""Streamlit UI — calls FastAPI only, never imports graph code."""
from __future__ import annotations

import json
import time

import httpx
import streamlit as st

API = "http://localhost:8000"


def api(method: str, path: str, **kwargs):
    try:
        r = getattr(httpx, method)(f"{API}{path}", timeout=30, **kwargs)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        st.error(f"API error {e.response.status_code}: {e.response.text}")
        return None
    except Exception as e:
        st.error(f"Cannot connect to API: {e}")
        return None


# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Meeting-to-Action Agent", page_icon="🤖", layout="wide")
st.title("🤖 Meeting-to-Action Agent")

# ── Session state init ────────────────────────────────────────────────────────

if "meeting_id" not in st.session_state:
    st.session_state.meeting_id = None
if "page" not in st.session_state:
    st.session_state.page = "upload"
if "last_status" not in st.session_state:
    st.session_state.last_status = None


def go(page: str):
    st.session_state.page = page
    st.rerun()


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Navigation")
    if st.button("📤 New Meeting", use_container_width=True):
        st.session_state.meeting_id = None
        go("upload")
    if st.session_state.meeting_id:
        st.info(f"Meeting #{st.session_state.meeting_id}")
        mid = st.session_state.meeting_id
        m = api("get", f"/meetings/{mid}")
        if m:
            status = m["status"]
            color = {"processing": "🔄", "needs_clarification": "❓", "awaiting_approval": "✅",
                     "executing": "⚙️", "done": "✅", "failed": "❌"}.get(status, "•")
            st.write(f"{color} **{status}**")

    st.markdown("---")
    st.subheader("📋 All Meetings")
    meetings = api("get", "/meetings") or []
    for m in meetings[:10]:
        label = f"#{m['id']} {m['title'][:30]} — {m['status']}"
        if st.button(label, key=f"m_{m['id']}", use_container_width=True):
            st.session_state.meeting_id = m["id"]
            _status = m["status"]
            if _status in ("needs_clarification",):
                go("clarify")
            elif _status in ("awaiting_approval",):
                go("approve")
            elif _status in ("done", "failed"):
                go("results")
            else:
                go("upload")


# ── Page: Upload ──────────────────────────────────────────────────────────────

def page_upload():
    st.header("📤 Upload Meeting Transcript")
    col1, col2 = st.columns([2, 1])

    with col2:
        st.subheader("Meeting Details")
        title = st.text_input("Meeting title", value="Team Sync")
        meeting_date = st.date_input("Meeting date")
        attendees_str = st.text_input("Attendees (comma-separated)", placeholder="Alice, Bob, Ravi")
        attendees = [a.strip() for a in attendees_str.split(",") if a.strip()]

    with col1:
        st.subheader("Transcript")
        tab_file, tab_paste = st.tabs(["Upload File", "Paste Text"])

        transcript = ""
        with tab_file:
            uploaded = st.file_uploader("Upload .txt, .vtt, or .srt", type=["txt", "vtt", "srt"])
            if uploaded:
                transcript = uploaded.read().decode("utf-8", errors="replace")
                st.text_area("Preview", transcript[:500] + ("..." if len(transcript) > 500 else ""), height=200, disabled=True)

        with tab_paste:
            pasted = st.text_area("Paste transcript here", height=300, placeholder="Alice: Let's discuss the sprint...\nBob: I'll handle the API by next Friday.")
            if pasted.strip():
                transcript = pasted

    if st.button("🚀 Process Meeting", type="primary", disabled=not transcript.strip()):
        payload = {
            "transcript": transcript,
            "title": title,
            "meeting_date": meeting_date.isoformat(),
            "attendees": attendees,
        }
        result = api("post", "/meetings", json=payload)
        if result:
            st.session_state.meeting_id = result["meeting_id"]
            st.success(f"Meeting #{result['meeting_id']} created! Processing...")
            go("polling")


# ── Page: Polling ─────────────────────────────────────────────────────────────

def page_polling():
    mid = st.session_state.meeting_id
    if not mid:
        go("upload")
        return

    st.header("⏳ Processing...")
    placeholder = st.empty()

    for _ in range(60):  # poll up to 2 minutes
        m = api("get", f"/meetings/{mid}")
        if not m:
            break
        status = m["status"]
        placeholder.info(f"Status: **{status}**")

        if status == "needs_clarification":
            go("clarify")
        elif status == "awaiting_approval":
            go("approve")
        elif status == "done":
            go("results")
        elif status == "failed":
            st.error(f"Processing failed: {m.get('error', 'unknown error')}")
            break

        time.sleep(2)
        st.rerun()

    st.warning("Processing is taking longer than expected. Please refresh.")


# ── Page: Clarify ─────────────────────────────────────────────────────────────

def page_clarify():
    mid = st.session_state.meeting_id
    if not mid:
        go("upload")
        return

    st.header("❓ Clarification Needed")
    st.info("The agent couldn't automatically determine some details. Please answer the questions below.")

    data = api("get", f"/meetings/{mid}/questions")
    if not data:
        return

    questions = data.get("questions", [])
    if not questions:
        st.success("No questions pending.")
        go("approve")
        return

    answers = {}
    with st.form("clarify_form"):
        for q in questions:
            st.markdown(f"**{q['text']}**")
            if q["kind"] == "date":
                val = st.date_input("Date", key=f"q_{q['id']}")
                answers[q["id"]] = val.isoformat()
            elif q["kind"] == "choice" and q.get("options"):
                val = st.radio("Choose:", q["options"], key=f"q_{q['id']}")
                answers[q["id"]] = val
            else:
                val = st.text_input("Answer:", key=f"q_{q['id']}")
                answers[q["id"]] = val
            st.markdown("---")

        if st.form_submit_button("Submit Answers", type="primary"):
            payload = {"answers": [{"question_id": qid, "value": v} for qid, v in answers.items()]}
            result = api("post", f"/meetings/{mid}/answers", json=payload)
            if result:
                go("polling")


# ── Page: Approve ─────────────────────────────────────────────────────────────

def page_approve():
    mid = st.session_state.meeting_id
    if not mid:
        go("upload")
        return

    st.header("✅ Review & Approve Plan")
    m = api("get", f"/meetings/{mid}")
    if m:
        st.caption(f"Meeting: **{m['title']}** | Date: {m['meeting_date']}")

    data = api("get", f"/meetings/{mid}/plan")
    if not data:
        return

    actions = data.get("actions", [])
    if not actions:
        st.info("No actions to approve.")
        return

    st.markdown(f"**{len(actions)} proposed action(s)** — approve, edit, or reject each one:")

    decisions: dict[str, dict] = {}

    for i, action in enumerate(actions):
        atype = action["type"]
        payload = action.get("payload", {})
        icon = {"create_task": "📋", "draft_email": "📧", "create_event": "📅", "record_decision": "📝"}.get(atype, "•")

        with st.expander(f"{icon} {atype.replace('_', ' ').title()} — {_action_summary(atype, payload)}", expanded=True):
            if action.get("warnings"):
                for w in action["warnings"]:
                    st.warning(w)

            st.json(payload, expanded=False)

            col_a, col_e, col_r = st.columns(3)
            dec = "approve"
            edit_data = {}

            with col_a:
                if st.button("✅ Approve", key=f"ap_{action['id']}"):
                    decisions[action["id"]] = {"decision": "approve"}
            with col_e:
                if st.button("✏️ Edit", key=f"ed_{action['id']}"):
                    st.session_state[f"edit_{action['id']}"] = True
            with col_r:
                if st.button("❌ Reject", key=f"rj_{action['id']}"):
                    decisions[action["id"]] = {"decision": "reject"}

            if st.session_state.get(f"edit_{action['id']}"):
                edit_json = st.text_area(
                    "Edit payload (JSON):",
                    value=json.dumps(payload, indent=2),
                    key=f"ej_{action['id']}",
                    height=150,
                )
                if st.button("Save Edit", key=f"se_{action['id']}"):
                    try:
                        edited = json.loads(edit_json)
                        decisions[action["id"]] = {"decision": "edit", "edits": edited}
                        st.session_state[f"edit_{action['id']}"] = False
                    except json.JSONDecodeError:
                        st.error("Invalid JSON")

    st.markdown("---")
    col_bulk, col_exec = st.columns(2)

    with col_bulk:
        if st.button("✅ Approve All", use_container_width=True):
            for action in actions:
                api("post", f"/meetings/{mid}/actions/{action['id']}/decision", json={"decision": "approve"})
            go("execute")

    with col_exec:
        if st.button("🚀 Execute Approved", type="primary", use_container_width=True):
            # Submit any staged decisions
            for aid, d in decisions.items():
                api("post", f"/meetings/{mid}/actions/{aid}/decision", json=d)
            go("execute")


def _action_summary(atype: str, payload: dict) -> str:
    if atype == "create_task":
        return f"{payload.get('title', '')[:50]} → {payload.get('owner_name', 'unassigned')}"
    if atype == "draft_email":
        return f"To: {', '.join(payload.get('to', []))}"
    if atype == "create_event":
        return payload.get("title", "")[:50]
    if atype == "record_decision":
        return payload.get("text", "")[:50]
    return ""


# ── Page: Execute ─────────────────────────────────────────────────────────────

def page_execute():
    mid = st.session_state.meeting_id
    if not mid:
        go("upload")
        return

    st.header("⚙️ Executing...")
    result = api("post", f"/meetings/{mid}/execute")
    if result:
        st.info("Execution started. Waiting for completion...")
        go("polling")
    else:
        st.error("Failed to start execution.")


# ── Page: Results ─────────────────────────────────────────────────────────────

def page_results():
    mid = st.session_state.meeting_id
    if not mid:
        go("upload")
        return

    st.header("📊 Results")
    m = api("get", f"/meetings/{mid}")
    if m:
        status = m["status"]
        if status == "done":
            st.success(f"✅ Meeting processed successfully!")
        elif status == "failed":
            st.error(f"❌ Processing failed: {m.get('error', '')}")
        else:
            st.info(f"Status: {status}")
        st.caption(f"**{m['title']}** | {m['meeting_date']}")

    tab_results, tab_tasks, tab_log, tab_items = st.tabs(["Execution Results", "Task Tracker", "Audit Log", "Extracted Items"])

    with tab_results:
        data = api("get", f"/meetings/{mid}/results")
        if data:
            for r in data.get("results", []):
                icon = {"executed": "✅", "skipped": "⏭️", "failed": "❌", "not_run": "⬜"}.get(r["execution_status"], "•")
                st.markdown(f"{icon} **{r['type']}** — {r['decision']} — {r['execution_status']}")
                if r.get("result"):
                    st.json(r["result"], expanded=False)

    with tab_tasks:
        tasks = api("get", f"/tasks?meeting_id={mid}") or []
        if tasks:
            for t in tasks:
                st.markdown(f"📋 **{t['title']}** | Owner: {t.get('owner_name', '—')} | Due: {t.get('due_date', '—')} | Status: {t['status']}")
                cols = st.columns(4)
                for j, s in enumerate(["open", "in_progress", "done", "cancelled"]):
                    if cols[j].button(s, key=f"ts_{t['id']}_{s}"):
                        api("patch", f"/tasks/{t['id']}", json={"status": s})
                        st.rerun()
        else:
            st.info("No tasks created yet.")

    with tab_log:
        log_data = api("get", f"/meetings/{mid}/log")
        if log_data:
            for entry in log_data.get("log", []):
                st.markdown(f"`{entry['ts'][:19]}` **[{entry['actor']}]** {entry['event']}")
                if entry.get("detail"):
                    st.json(entry["detail"], expanded=False)

    with tab_items:
        items = api("get", f"/meetings/{mid}/items")
        if items:
            st.subheader("Decisions")
            for d in items.get("decisions", []):
                st.markdown(f"📝 {d['text']}")
                st.caption(f"Quote: *\"{d.get('quote', '')}\"*")
            st.subheader("Tasks")
            for t in items.get("tasks", []):
                st.markdown(f"📋 **{t['title']}** — {t.get('owner_name', '—')}")


# ── Router ─────────────────────────────────────────────────────────────────────

page = st.session_state.page

if page == "upload":
    page_upload()
elif page == "polling":
    page_polling()
elif page == "clarify":
    page_clarify()
elif page == "approve":
    page_approve()
elif page == "execute":
    page_execute()
elif page == "results":
    page_results()
else:
    page_upload()
