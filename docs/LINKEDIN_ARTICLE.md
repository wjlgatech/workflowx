# LinkedIn Article
## Title: I Was in a Client Meeting. My AI Wasn't Allowed. So I Built Something Better.

---

Last Tuesday I was deep in a client meeting — Accenture engagement, sensitive context, no Microsoft Copilot allowed on the call.

My notes were falling behind. An action item slipped by. I missed the moment to ask the right question.

That night, I thought: *what would it actually mean to have an AI that helps me in meetings?*

And then I thought harder — and realized I'd been asking the wrong question entirely.

---

**The wrong question: "How do I get AI into the room?"**

The obvious answer is always "ambient AI." A tool that sees what you see, hears what you hear, runs in the background, whispers advice in real time.

I dug into it seriously. Built the cost model. Researched the legal landscape. And found three walls you don't see until you're standing right in front of them.

**Wall 1: Latency.**
Real-time voice suggestions need to arrive in under 300 milliseconds to feel natural. Claude's computer-use cycle takes 2–5 seconds. You're not getting a whisper. You're getting a tap on the shoulder after the moment has passed.

**Wall 2: Law.**
Twelve states — California, Florida, Illinois, Washington, Massachusetts, and seven others — require all-party consent to record a conversation. A silent AI tool that transcribes without disclosure isn't a productivity hack. It's a felony.

**Wall 3: Cost.**
Continuous ambient reasoning at current LLM rates runs $1–3 per hour. Multiply by a 40-hour week of call-heavy work. That's not a tool budget. That's a salary line.

Three walls. Three reasons why every "ambient AI" pitch you've heard in the past two years has quietly died in the pilot.

---

**The right question: "Where does intelligence actually compound?"**

Close your eyes. Think about the last client meeting where something went wrong.

It wasn't during the meeting. It was before it — you didn't know their recent news, you hadn't scanned the email thread, you walked in without a crisp agenda. Or it was after — you forgot what you promised, you sent the follow-up email three days late, the action item fell through the cracks.

The meeting itself was fine. The bookends failed.

That's the insight. Intelligence at the edges of a meeting compounds. Intelligence during a meeting is mostly noise.

So I stopped trying to build ambient AI. And I built a Meeting Intelligence Stack instead.

---

**Three phases. Five MCP tools. $2.35/month.**

Here's what I built into WorkflowX (open source, MIT, on GitHub):

**Phase 1: Post-Meeting Debrief**

You finish a meeting. You dump your raw notes — a paragraph, some bullets, a fragment of a transcript — into one command:

```
workflowx_meeting_debrief
```

Claude Haiku processes them and returns:
- What was actually discussed (3–5 bullets, no filler)
- Commitments — what *you* promised, what *they* promised, as separate lists
- Action items with owners and deadlines, parsed into a table
- A follow-up email draft, pushed straight to Gmail Drafts

You review it in 90 seconds. You hit send. You move on.

Cost per meeting: $0.02. Time saved per meeting: 25–30 minutes.

**Phase 2: Pre-Meeting Brief**

Every night at 11 PM, the system scans tomorrow's calendar. For each external meeting, it:
- Searches your Gmail for prior threads with those attendees
- Pulls relevant Google Drive documents
- Searches the web for recent company news
- Synthesizes a 1-page cheat sheet

The brief is in your Projects folder by 6 AM. You read it while you're walking. You walk into the meeting already holding the context.

The magic isn't the brief. It's the compounding. Every debrief from Phase 1 becomes context for the next Phase 2 brief. After 30 meetings, the system knows your clients better than most CRMs.

**Phase 3: Real-Time Sidebar (internal meetings only)**

For internal calls — your team, your co-founders, your direct reports — there's no consent issue. So you get the thing close to ambient AI: a 30-second refresh that shows the last 90 seconds of transcript and suggests one specific question to ask.

Not "can you elaborate?" A real question, grounded in what was just said.

The consent_guard.py module enforces the rule automatically: if an external attendee is detected in the calendar event, the sidebar blocks. If you've added "AI may assist" to the meeting description and told the attendees at the start, it unblocks.

The legal wall is enforced in code, not policy.

---

**The flywheel no one talks about**

Here's what surprises me most, a week in.

The value isn't any individual feature. It's that the three phases talk to each other.

Debrief captures what was promised. Pre-Brief uses that history. Sidebar watches for new promises being made. Action items flow automatically to TASKS.md.

After ten meetings, you're not working harder. You're working with better memory — a second brain that was actually in the room.

---

**The uncomfortable truth about AI in meetings**

We've been sold a vision of AI as a co-pilot that's always present, always listening, always ready with an insight.

That vision runs into physics (latency), law (consent), and economics (cost). Every time.

The version that actually works is quieter. It does the legwork before you walk in. It catches everything after you walk out. And it stays out of the room while you're doing the work that only you can do: reading the room, building trust, making decisions.

That's not a lesser version of the AI-in-meetings dream. It's the version that compounds.

---

**It's open source. Try it.**

WorkflowX is MIT-licensed. The Meeting Intelligence Stack is in the latest version. Five new MCP tools, 23 tests, $0.03 per meeting, zero legal exposure.

GitHub: **github.com/wjlgatech/workflowx**

If you're in a meeting-heavy role — sales, consulting, product, leadership — I'd genuinely like to know what Phase 1 saves you on your first debrief.

The wall that stops most AI tools is the gap between the demo and the real meeting room.

This one is designed for the real room.

---

*WorkflowX is an open-source workflow intelligence platform. It observes workflows, infers intent, proposes replacements, and measures ROI — locally, privately, without surveillance.*
