# Social Posts — Meeting Intelligence Stack Launch

---

## LinkedIn (long-form post — paste into LinkedIn post composer)

I was in a client meeting last week. Sensitive engagement — no Microsoft Copilot allowed.

My notes fell behind. An action item slipped by. I missed the moment to ask the right question.

So I built something. But first I had to kill an idea.

**The idea I killed: ambient AI.**

The pitch is always the same — an AI that sees what you see, hears what you hear, runs in the background, whispers advice in real time. I took that pitch seriously. Built the cost model. Researched the law. Found three walls.

**Wall 1: Latency.** Real-time suggestions need to land in <300ms. Claude's cycle is 2–5 seconds. That's not a whisper. That's a tap on the shoulder after the moment has passed.

**Wall 2: Law.** 12 states require all-party consent to record. California. Florida. Illinois. Washington. A silent AI tool that transcribes without disclosure isn't a productivity hack — it's a felony.

**Wall 3: Cost.** Continuous ambient reasoning at current LLM rates runs $1–3/hour. Multiply by a meeting-heavy week. That's not a tool budget. That's a salary line.

Three walls. Three reasons why every "ambient AI in meetings" product you've heard of has quietly died in the pilot.

---

The right question isn't "how do I get AI into the room?" It's: **"where does intelligence actually compound?"**

Think about the last meeting that went wrong. It wasn't during the meeting. It was before — you didn't know their recent news, you walked in cold. Or it was after — you forgot what you promised, the action item fell through.

The bookends failed. The meeting itself was fine.

So I built a Meeting Intelligence Stack instead. Three phases:

**Phase 1 — After the meeting:** You dump raw notes into one command. Claude Haiku returns:
- What was actually discussed (3–5 bullets, no filler)
- What *you* promised vs. what *they* promised
- Action items with owners and deadlines
- Follow-up email draft → straight to Gmail Drafts

Cost: $0.02 per meeting. Time saved: 25–30 min.

**Phase 2 — Before the meeting:** The night before, the system scans your calendar. For each external meeting: Gmail history, Drive docs, company news, attendee profiles → 1-page cheat sheet. Ready at 6 AM before you start your day.

**Phase 3 — During internal meetings only:** A 30-second sidebar refresh shows the last 90 seconds of transcript and suggests one specific question. Internal only — `consent_guard.py` blocks external meetings automatically. The legal wall is enforced in code, not policy.

---

The flywheel nobody talks about: each debrief feeds the next pre-brief. After 30 meetings, the system holds better institutional memory than most CRMs.

Total cost: ~$2.35/month. Break-even: the first meeting.

It's open source. MIT license. In the latest WorkflowX release.

👉 github.com/wjlgatech/workflowx

What does your post-meeting workflow cost you right now?

---

## X / Twitter Post 1 — "The 3 walls" (hook on insight)

Ambient AI in meetings sounds great.

Then you run the numbers.

→ Latency: needs <300ms. Claude takes 2-5s. The moment has passed.
→ Law: 12 states need all-party consent. Silent transcription = felony in CA.
→ Cost: $1-3/hr continuous. That's a salary, not a tool.

So I stopped trying to put AI in the room.

And built something that works at the edges instead.

Before + after > ambient.

🧵 How I built the Meeting Intelligence Stack into @workflowx (open source):

---

## X / Twitter Post 2 — "The cost reveal" (hook on price)

I automated 3 phases of meeting intelligence.

Total cost: $2.35/month.

Phase 1 — Post-meeting debrief
Raw notes in → structured output out:
• What was discussed
• What YOU promised vs THEY promised
• Action items table
• Follow-up email draft → Gmail Drafts
Cost: $0.02 per meeting.

Phase 2 — Pre-meeting brief
Night before: calendar scan → Gmail + Drive + web → 1-page cheat sheet by 6am.
Compounds. After 30 meetings it knows your clients better than most CRMs.

Phase 3 — Real-time sidebar (internal only)
30s refresh. Last 90s of transcript. One suggested question.
consent_guard.py blocks external meetings. Legal wall in code, not policy.

Open source, MIT.
github.com/wjlgatech/workflowx

---

## X / Twitter Post 3 — "The flywheel" (hook on compounding)

Most productivity tools are speedometers.

They tell you how fast you were going.

WorkflowX Meeting Intelligence is a GPS that rebuilds the road.

Each debrief → feeds the next pre-brief
Each pre-brief → walks you in with full context
Each meeting → adds to what the next one knows

After 30 meetings, you're not working harder.
You're working with better memory.

The system that sees every promise made, every client thread, every open item — and puts it in front of you the night before you need it.

That's what compounds.

github.com/wjlgatech/workflowx — open source, MIT
