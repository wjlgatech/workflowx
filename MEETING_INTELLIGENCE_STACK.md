# Meeting Intelligence Stack
*Status: ACTIVE BUILD — v0.1 | Owner: Wu | Started: 2026-04-06*

> Not ambient AI. Not always-watching. Smarter: bookend intelligence that compounds.
> Pre-brief → Meeting → Structured debrief → Next meeting is already smarter.

---

## Why This, Not Ambient AI

| Approach | Latency | Legal | Cost | Compounds? |
|----------|---------|-------|------|------------|
| Ambient real-time AI | 2–5s (unusable) | Illegal in 12 states | $1–3/hr | No |
| **Meeting Intelligence Stack** | Pre-computed | Zero risk | $0.03–0.08/meeting | **Yes** |

The window for ambient AI is closing — consent laws are tightening, not loosening. This stack delivers more value because it works *around* meetings, not inside them.

---

## Architecture

```
BEFORE MEETING          DURING MEETING         AFTER MEETING
─────────────────       ───────────────        ──────────────────────
Calendar event     →    [You focus,      →     workflowx_capture
  + Gmail threads        no AI needed]           + Claude Haiku
  + Drive docs                                    + Gmail draft
  + Web research                                  + TASKS.md update
         ↓                                              ↓
1-page cheat sheet                          Structured debrief saved
ready at 6 AM                               → feeds next pre-brief
```

---

## Phase 1: Post-Meeting Debrief (Week 1)
**Status:** 🔴 Building
**ROI:** ~30 min saved per meeting. Break-even on first use.

### What it does
After any meeting, Wu runs one command. Claude Haiku processes the raw notes/transcript and produces:
1. What was discussed (3–5 bullets, no fluff)
2. What was committed/promised (by Wu, by them)
3. Action items with owners and deadlines
4. Follow-up email draft → pushed to Gmail Drafts

### Trigger
```
workflowx_capture --meeting "client name or topic" --notes "raw dump"
```
Or: paste meeting notes directly into Claude. Skill auto-detects and runs debrief flow.

### Output format
```markdown
## Meeting: [Client/Topic] — [Date]
### Discussed
- ...

### Commitments
- **Wu:** ...
- **Them:** ...

### Actions
| Owner | Action | Deadline |
|-------|--------|----------|

### Follow-up email
Subject: Re: [topic]
[Draft body]
```

### Files
- `src/debrief/debrief_agent.py` — main agent
- `src/debrief/prompt_templates.py` — Haiku system prompt + output schema
- `src/debrief/gmail_push.py` — Gmail draft creation via MCP
- `src/debrief/tasks_updater.py` — appends action items to TASKS.md
- `tests/test_debrief.py`

### Acceptance criteria
- [ ] Given raw meeting notes → structured markdown output in <10s
- [ ] Follow-up email draft appears in Gmail Drafts within 30s
- [ ] Action items appended to Projects/TASKS.md
- [ ] Works with meeting notes of any format (freeform prose, bullet dump, partial transcript)

---

## Phase 2: Pre-Meeting Brief (Week 2)
**Status:** 🔴 Not started
**ROI:** 15–20 min saved per external meeting. Enters meeting with full context.

### What it does
Every night at 11 PM (or on-demand), scans next day's calendar. For each external meeting:
1. Pulls Gmail thread history with that person/company
2. Searches Drive for relevant docs
3. Web-searches company for recent news
4. Generates 1-page cheat sheet

Brief is ready in Projects/workflowx/briefs/YYYY-MM-DD-[client].md by 6 AM.

### Trigger
```
workflowx_propose --date tomorrow
```
Or: automated via scheduled task at 11 PM nightly.

### Output format
```markdown
## Pre-Brief: [Client] — [Meeting time]
### Who
[Name, title, company, LinkedIn summary]

### Last touchpoint
[Last email/meeting, key context]

### Open items
[What they're waiting on from Wu, what Wu is waiting on from them]

### Company pulse
[Recent news, funding, product launches]

### Suggested agenda
1. ...
2. ...

### One thing to say, one thing to ask
- Say: ...
- Ask: ...
```

### Files
- `src/prebrief/brief_agent.py` — orchestrator
- `src/prebrief/calendar_scanner.py` — gcal event detection + attendee extraction
- `src/prebrief/context_gatherer.py` — Gmail + Drive + web search
- `src/prebrief/brief_writer.py` — Claude Haiku synthesis → markdown
- `src/prebrief/scheduler.py` — 11 PM nightly scheduled task
- `tests/test_prebrief.py`

### Acceptance criteria
- [ ] Detects external meetings on tomorrow's calendar
- [ ] Generates brief within 60s per meeting
- [ ] Brief saved to workflowx/briefs/ and accessible by 6 AM
- [ ] Handles case where no prior email history exists (graceful fallback)

---

## Phase 3: Real-Time Sidebar (Weeks 3–5)
**Status:** 🔴 Not started
**Constraint:** Internal meetings ONLY. No external parties without consent.
**ROI:** One suggested question per 30s. Catches things Wu would miss at 2 PM.

### What it does
During internal meetings (Accenture team calls, co-founder syncs), a sidebar refreshes every 30 seconds:
- Shows last 3 exchanges from transcript
- Suggests one question or flag
- Flags commitments made in real-time

### Tech stack
- **Audio capture:** Screenpipe (local, no cloud, no consent issue for internal)
- **Transcription:** Whisper (local, ~2s latency per chunk)
- **Reasoning:** Claude Haiku API (30s context window refresh)
- **Display:** Minimal floating HTML overlay (always on top, low opacity)

### Legal boundary
```
✅ Internal meetings (same company) — no consent required
✅ One-on-one calls where Wu is a party — varies by state, disclose at start
❌ External client meetings without "AI may be assisting" disclosure
```

### Files
- `src/sidebar/audio_capture.py` — Screenpipe integration
- `src/sidebar/transcriber.py` — Whisper local inference
- `src/sidebar/sidebar_agent.py` — 30s refresh → Haiku call → suggestion
- `src/sidebar/overlay.py` — floating HTML window
- `src/sidebar/consent_guard.py` — blocks if calendar event has external attendees
- `tests/test_sidebar.py`

### Acceptance criteria
- [ ] Transcription lag < 5s
- [ ] Suggestion refreshes every 30s, never blocks Wu
- [ ] consent_guard correctly classifies internal vs external
- [ ] Can be toggled on/off with hotkey

---

## Stack Dependencies

| Tool | Phase | Purpose |
|------|-------|---------|
| Claude Haiku API | 1, 2, 3 | Reasoning (cheap, fast) |
| Gmail MCP | 1, 2 | Read threads + push drafts |
| Google Calendar MCP | 2, 3 | Event detection + attendee info |
| Google Drive MCP | 2 | Pull relevant docs |
| WebSearch | 2 | Company pulse |
| Screenpipe | 3 | Local audio capture |
| Whisper (local) | 3 | Transcription |
| workflowx MCP | 1, 2, 3 | Capture, analyze, propose, measure |

---

## Cost Model

| Phase | Cost per meeting | Meetings/month | Monthly cost |
|-------|-----------------|----------------|--------------|
| Phase 1 (debrief) | ~$0.02 | 20 | ~$0.40 |
| Phase 2 (pre-brief) | ~$0.05 | 15 | ~$0.75 |
| Phase 3 (sidebar) | ~$0.15/hr × 1hr | 8 internal | ~$1.20 |
| **Total** | | | **~$2.35/month** |

Break-even: **first meeting.**

---

## Build Order & Ownership

```
Week 1:  Phase 1 — debrief_agent + gmail_push + tasks_updater
Week 2:  Phase 2 — brief_agent + calendar_scanner + context_gatherer
Week 3:  Phase 3 (setup) — Screenpipe install + Whisper integration
Week 4:  Phase 3 (sidebar) — overlay + consent_guard + 30s loop
Week 5:  Integration + testing + workflowx_measure instrumentation
```

---

## Flywheel

Each meeting feeds the next:
```
Debrief (Phase 1)
  → action items in TASKS.md
  → email history for next pre-brief (Phase 2)
  → patterns in workflowx_patterns
  → sidebar gets smarter on this client (Phase 3)
```

After 30 meetings, the system knows Wu's clients better than most CRMs.

---

*This document is the spec. gstack agents build from this. Wu reviews only for critical decisions.*
