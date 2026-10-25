# Faculty Presentation Guide — Meeting-to-Action Agent

This guide walks you through how to present and demo the project to your faculty. Estimated demo time: 15–20 minutes.

---

## 1. Opening — Problem Statement (2 minutes)

**What to say:**

> "Every meeting ends with commitments and decisions. But research shows that 40–60% of meeting action items are never completed — not because people don't care, but because they're not tracked, the owner is unclear, or the deadline was vague. This project automates that tracking process using an agentic AI pipeline."

**Key points to hit:**
- The problem is not note-taking — it's *structured extraction* with *accountability*
- Existing tools (Otter.ai, Notion AI) produce raw summaries; this produces *verified, human-approved tasks* ready to track
- The system never creates a task without human approval

---

## 2. Architecture Explanation (3 minutes)

**Draw this on the whiteboard as you explain:**

```
Transcript → Extractor → Validator → [Clarify?] → Planner → [Approve?] → Executor → DB
```

**How to explain each node:**

1. **Extractor**: "The LLM reads the transcript and finds what looks like tasks and decisions. It also quotes the exact sentence from the transcript — we call this quote grounding."

2. **Validator**: "The system checks 8 rules: Does the quote actually exist in the transcript? Is there an owner? Is the deadline specific? Is it a duplicate of something already tracked? If something is wrong, the system either retries the LLM or asks the human."

3. **Clarify node**: "This is where the agent *pauses* and asks the user to fill in missing information — like who owns a task or what exactly 'soon' means."

4. **Planner**: "Creates a structured plan: which tasks to create, which emails to draft, which decisions to record."

5. **Approval node**: "The agent pauses again and shows the human every proposed action. Nothing executes without approval."

6. **Executor**: "The only node that writes to the database. It only runs for approved actions. It's idempotent — running it twice is safe."

**Key concept to emphasize:** "This is called *human-in-the-loop*. The agent does the analysis but the human has the final say."

---

## 3. Live Demo (8 minutes)

**Prerequisites (do this before the presentation):**
```bash
uvicorn app.api.main:app --reload --port 8000   # terminal 1
streamlit run ui/app.py                          # terminal 2
```
Open http://localhost:8501 in your browser.

### Step 1: Upload the transcript (1 min)
- In the Streamlit UI, click "Paste transcript"
- Paste the contents of `eval/transcripts/01_sprint_planning.txt`
- Set meeting date to today
- Click Submit

**Say:** "The system is now running the extraction pipeline in the background."

### Step 2: Watch it process (30 sec)
- The UI auto-refreshes every 2 seconds
- Status goes: `processing` → `needs_clarification`

**Say:** "The validator found some problems — 'Sam' is ambiguous because we have both Sam Johnson and Sam Lee in our system. There's also a task with no deadline."

### Step 3: Answer clarification questions (2 min)
- The Clarify page shows each question
- For Sam: select which Sam from the dropdown
- For missing deadline: enter a date
- For vague deadline: enter a specific date
- Click Submit

**Say:** "This is the first human-in-the-loop gate. The agent can't proceed until the human resolves the ambiguities."

### Step 4: Review and approve the plan (3 min)
- Status moves to `awaiting_approval`
- Click the Approve tab to see proposed actions
- Show each card: task creation, email draft, calendar event
- Approve most, reject one (e.g., the CI task with no owner)
- Click "Execute Approved Actions"

**Say:** "This is the second human-in-the-loop gate. Every action is visible before anything is committed."

### Step 5: View results (1 min)
- Status moves to `done`
- Show the Results tab: which actions executed
- Show the Task Tracker tab: new tasks in the DB
- Show the Audit Log tab: every event recorded

**Say:** "Everything is logged — who approved what, when, and what the system did. The audit log is append-only — it cannot be modified."

---

## 4. Agentic AI Concepts Demonstrated (3 minutes)

Explain how this project demonstrates each agentic AI concept:

### Human-in-the-Loop
> "Most AI systems are fire-and-forget. This system is different — it pauses twice and waits for human input before taking any action. LangGraph's `interrupt()` function implements this pattern. The graph literally stops executing and persists its state until the human responds."

### Stateful Agent
> "The agent's state is persisted in SQLite using LangGraph's SqliteSaver. If you restart the server mid-conversation, the agent can resume exactly where it left off. The `thread_id` links each conversation to its checkpoint."

### Tool Use
> "The agent uses deterministic tools: a transcript parser, a date resolver, and a task database. Notice that the LLM never resolves dates — we use a rule-based resolver. This eliminates a common source of hallucination."

### Structured Outputs
> "Every LLM response is validated against a Pydantic schema. If the LLM returns malformed JSON, the system retries up to 2 times with an error correction prompt."

### Agentic Loop
> "The Validator→Re-extract cycle is a classic agentic loop — the agent detects a problem, corrects it, and validates again. The retry cap (2 attempts) prevents infinite loops."

---

## 5. Anticipated Faculty Questions

**Q: Why not just use ChatGPT to summarize the meeting?**
> "ChatGPT gives you a summary, not structured data. This system gives you actual database rows — tasks with owners and deadlines — ready to track in a project management tool. It also enforces validation rules: no task without a quote, no ambiguous owners."

**Q: What happens if the LLM hallucinates a task?**
> "Two defenses: First, quote grounding — every extracted task must have a verbatim substring from the transcript, or it fails validation. Second, human approval — even if something gets through, the human sees it and can reject it."

**Q: How does the system know who 'Sam' is?**
> "The `people` table stores known names and aliases. The `resolve_person()` function checks all aliases. If there are multiple matches — like Sam Johnson and Sam Lee — it returns count=2 and triggers the AMBIGUOUS_OWNER clarification question."

**Q: What if the same task is submitted twice?**
> "The system computes a fingerprint — a hash of the normalized title and owner. It also computes Jaccard similarity between word sets. A similarity above 0.8 triggers a duplicate warning; the human decides whether to merge or create separately."

**Q: Is this production-ready?**
> "Not yet — the email and calendar are mocks, the LLM calls would need rate limiting and cost controls, and the UI needs proper authentication. But the architecture patterns — interrupt/resume, idempotent execution, append-only audit log — are all production patterns."

**Q: How does the agent handle different transcript formats?**
> "The transcript parser supports four formats: plain speaker labels, timestamped, WebVTT (used by Zoom/Teams), and SRT (subtitle format). It auto-detects the format."

**Q: What's the difference between `needs_clarification` and `awaiting_approval`?**
> "Clarification happens before planning — it's asking the human to fill in missing information so the plan can be correct. Approval happens after planning — the human reviews the complete plan and decides what to execute. They're two distinct human-in-the-loop gates with different purposes."

---

## 6. Key Metrics to Mention

If asked about evaluation results, use these numbers from the eval transcript:
- **Tasks planted in demo transcript:** 8
- **Edge cases:** 8 (ambiguous owner, duplicate, missing owner, vague deadline, missing deadline, self-commitment, stop label, calendar event trigger)
- **Validation checks:** 8 rule types
- **Graph nodes:** 6
- **Lines of code:** ~1,500 (excluding tests and docs)
- **Test coverage:** 39 unit tests across 4 test files

---

## 7. Closing (1 minute)

**What to say:**

> "The key insight is that agentic AI isn't just about automation — it's about designing the right interaction model between the human and the agent. This system is valuable not because it removes the human from the loop, but because it structures the human's role: review the analysis, answer the ambiguities, approve the plan. The agent handles the tedious extraction work; the human handles the judgment calls."
