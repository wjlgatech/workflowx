<p align="center">
  <img src="docs/logo.png" alt="WorkflowX" width="120" />
</p>

<h1 align="center">WorkflowX</h1>

<p align="center">
  <strong>Stop guessing where your time goes. Start replacing what wastes it.</strong>
</p>

<p align="center">
  <a href="https://github.com/wjlgatech/workflowx/actions"><img src="https://github.com/wjlgatech/workflowx/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/wjlgatech/workflowx/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/status-alpha-orange" alt="Status: Alpha">
  <img src="https://img.shields.io/badge/privacy-local--first-green" alt="Privacy: Local-first">
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> &bull;
  <a href="#how-it-works">How It Works</a> &bull;
  <a href="#roadmap">Roadmap</a> &bull;
  <a href="#contributing">Contributing</a>
</p>

---

## The Problem

You know that feeling? You sat at your desk for 8 hours. You were *busy*. But what actually got done?

You switched between 14 apps. You copy-pasted the same data three times. You spent 40 minutes on a task that should have taken 5 — because the tool fought you. And you have no idea which 2 hours actually moved the needle.

Every productivity tool on the market shows you a time pie chart and says "good luck."

**WorkflowX does something different.** It doesn't just watch. It *understands* what you're trying to do, finds where you're bleeding time, and proposes workflows that achieve the same goal in a fraction of the time — not by speeding up the old way, but by reimagining the path entirely.

## What Makes This Different

| What Exists Today | What It Does | What It Can't Do |
|---|---|---|
| RescueTime, Toggl | Counts time per app | Doesn't know *why* you used the app |
| Hubstaff, ActivTrak | Screenshots your screen | Surveillance, not intelligence |
| Celonis | Mines ERP system logs | Can't see what humans actually do |
| Screenpipe | Records everything locally | Captures everything, understands nothing |

**WorkflowX sits in the gap.** It reads events from capture tools (Screenpipe, ActivityWatch), uses AI to infer *what you were trying to accomplish*, identifies friction, asks you one smart question to validate, then generates a replacement workflow that achieves your goal better.

```
Screenpipe (capture)  →  WorkflowX (understand + replace)  →  Agenticom (execute)
```

---

## How It Works

Close your eyes. Think about the last time you did "competitive research." You probably opened a dozen tabs, skimmed articles, copied quotes into a doc, forgot which tab had the good stat, went back, re-read, pasted, reformatted. An hour gone.

WorkflowX sees that trail of events and says:

> *"You spent 52 minutes across Chrome and Notion doing what looks like competitive research (confidence: 0.85). You switched apps 23 times. Estimated cost: $65.*
>
> *Proposed replacement: An Agenticom workflow that monitors these 12 competitor URLs, extracts pricing and feature changes daily, and delivers a structured brief to your Notion. Estimated time: 3 minutes/week. Savings: 49 minutes/week."*

That's the full loop:

```
OBSERVE  →  INFER INTENT  →  DIAGNOSE FRICTION  →  VALIDATE WITH USER  →  REPLACE  →  MEASURE
    ↑                                                                                      │
    └──────────────────────────────────────────────────────────────────────────────────────┘
```

Nobody else closes this loop. Activity trackers stop at OBSERVE. Process mining stops at DIAGNOSE. RPA stops at copying the old workflow. WorkflowX reimagines the workflow from the goal backward.

---

## Quickstart

### Prerequisites

- Python 3.10+
- [Screenpipe](https://github.com/mediar-ai/screenpipe) installed and running (for live capture)

### Install

```bash
git clone https://github.com/wjlgatech/workflowx.git
cd workflowx
pip install -e ".[all]"
```

### Use

```bash
# Check connection to Screenpipe
workflowx status

# Read today's events
workflowx capture --hours 8

# Analyze: cluster into sessions, infer intent
workflowx analyze --hours 8

# Generate daily/weekly report
workflowx report --period weekly

# Detect recurring patterns across 30 days
workflowx patterns --days 30

# See friction trends over 4 weeks
workflowx trends --weeks 4

# Generate replacement proposals
workflowx propose --top 3

# Track a replacement and measure ROI
workflowx adopt "competitive research" --before-minutes 50
workflowx measure --days 7

# Generate HTML ROI dashboard
workflowx dashboard -o roi.html

# Export data for external analysis
workflowx export --data sessions --format csv --days 30

# Start MCP server for Claude/Cursor
workflowx mcp
```

### Example Output

```
┌─────────────────────────────────────────────────────────────────┐
│                      Workflow Sessions                           │
├──────────┬──────────┬─────────────────┬──────────┬──────────────┤
│ Time     │ Duration │ Apps            │ Switches │ Friction     │
├──────────┼──────────┼─────────────────┼──────────┼──────────────┤
│ 09:15-10 │ 45 min   │ VSCode, Chrome  │ 4        │ low          │
│ 10:05-11 │ 62 min   │ Chrome, Notion  │ 23       │ critical     │
│ 11:30-12 │ 28 min   │ Slack, Zoom     │ 8        │ medium       │
│ 13:00-14 │ 55 min   │ VSCode, Term    │ 3        │ low          │
│ 14:10-15 │ 48 min   │ Chrome, Sheets  │ 19       │ high         │
└──────────┴──────────┴─────────────────┴──────────┴──────────────┘

Total tracked: 238 min
High-friction sessions: 2 (110 min) ← these are your replacement candidates
```

---

## Architecture

```
src/workflowx/
├── models.py              # 11 Pydantic domain models (the contract)
├── config.py              # Config from env vars / .env
├── storage.py             # Local JSON storage (privacy-first, file-per-day)
├── export.py              # JSON/CSV export for external analysis
├── measurement.py         # Before/after ROI tracking
├── dashboard.py           # Self-contained HTML ROI dashboard
├── mcp_server.py          # MCP server for Claude/Cursor integration
├── capture/               # Data source adapters
│   ├── screenpipe.py      # Screenpipe SQLite reader
│   └── activitywatch.py   # ActivityWatch REST API reader
├── inference/             # The intelligence layer ← OUR VALUE
│   ├── clusterer.py       # Raw events → workflow sessions
│   ├── intent.py          # LLM-based intent inference
│   ├── reporter.py        # Daily/weekly report generation
│   └── patterns.py        # Cross-day pattern detection + friction trends
├── replacement/           # Workflow reimagination engine
│   └── engine.py          # LLM-powered replacement proposals + Agenticom YAML
├── api/                   # FastAPI (dashboard, integrations)
└── cli/                   # Click CLI (12 commands)
```

**Design principles:**
- **Don't rebuild capture.** Screenpipe is MIT, 12.6k stars, cross-platform. Use it.
- **Local-first.** All data stays on your device. No cloud. No surveillance.
- **Models are the contract.** Everything flows through `models.py`.
- **LLM calls are isolated.** Only `inference/intent.py` talks to LLMs. Everything else is deterministic and testable.

---

## Roadmap

### Phase 1: Self-Awareness (v0.1) — *Complete*

- [x] Core domain models (8 Pydantic models)
- [x] Screenpipe capture adapter
- [x] ActivityWatch capture adapter
- [x] Session clustering with friction heuristics
- [x] LLM intent inference (Anthropic + OpenAI + Ollama)
- [x] Classification questions (user validation loop)
- [x] Daily + weekly workflow reports
- [x] Replacement engine with Agenticom YAML generation
- [x] Full CLI: `capture`, `analyze`, `validate`, `report`, `propose`, `status`
- [x] Local JSON storage (privacy-first, file-per-day)
- [x] Config from env vars (.env support)
- [x] 24 tests passing, CI pipeline

### Phase 2: Diagnosis (v0.2) — *Complete*

- [x] Pattern detection (recurring high-friction workflows across days)
- [x] Weekly friction trends (is friction going up or down?)
- [x] Workflow diagnosis engine (cost attribution, automation scoring)
- [x] Export to JSON / CSV for external analysis
- [x] MCP server (let Claude / Cursor query your workflow data)
- [x] CLI: `patterns`, `trends`, `export`, `mcp`
- [x] 63 tests passing

### Phase 3: Replacement (v0.3) — *Complete*

- [x] Replacement proposal engine
- [x] Agenticom workflow YAML generation
- [x] Before/after measurement (did the replacement actually save time?)
- [x] ROI dashboard (self-contained HTML with Chart.js)
- [x] Adoption tracking with cumulative savings
- [x] CLI: `adopt`, `measure`, `dashboard`
- [ ] OpenClaw integration (trigger replacements from Slack/WhatsApp)

### Phase 4: Team Intelligence (v0.4)

- [ ] Multi-user aggregation (team workflow graph)
- [ ] Bottleneck detection across team members
- [ ] Shared replacement library
- [ ] Privacy controls (aggregate-only team views)
- [ ] FastAPI dashboard

### Future

- [ ] More capture adapters: WakaTime, browser extension, calendar APIs
- [ ] Workflow marketplace (share/discover replacement workflows)
- [ ] Real-time streaming (live friction alerts)
- [ ] Self-improving inference (learn from user corrections)

---

## Why Open Source?

Because workflow data is the most intimate data you have after your health records. If your workflow intelligence tool isn't open source and local-first, you shouldn't use it. Period.

WorkflowX will always be:
- **MIT licensed** — use it however you want
- **Local-first** — your data never leaves your device
- **Open source** — audit every line that touches your data

---

## Contributing

We're building this in public and we want contributors who care about:

1. **Privacy-first workflow intelligence** — not surveillance
2. **AI that replaces work, not just reports on it**
3. **Clean, tested, composable code**

```bash
git clone https://github.com/wjlgatech/workflowx.git
cd workflowx
make install-dev
make test   # all green? you're ready
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

**Good first issues:**
- Add ActivityWatch capture adapter
- Add WakaTime capture adapter
- Improve friction heuristics with real user data
- Build browser extension for richer URL/tab data

---

## Comparison

| Feature | WorkflowX | RescueTime | Screenpipe | Celonis | ActivTrak |
|---|---|---|---|---|---|
| Privacy (local-first) | **Yes** | No | **Yes** | No | No |
| Intent inference | **Yes** | No | No | No | No |
| User validation loop | **Yes** | No | No | No | No |
| Workflow replacement | **Yes** | No | No | No | No |
| ROI measurement | **Yes** | No | No | Partial | Partial |
| Open source | **MIT** | No | **MIT** | No | No |
| Agent integration | **Agenticom** | No | MCP | No | No |
| Price | **Free** | $12/mo | Free | $$$$$ | $10-19/mo |

---

## Star History

If this solves a real problem for you, star the repo. It helps others find it.

---

<p align="center">
  <strong>Built by <a href="https://github.com/wjlgatech">@wjlgatech</a></strong><br>
  <em>Observe. Understand. Replace. Measure. Repeat.</em>
</p>
