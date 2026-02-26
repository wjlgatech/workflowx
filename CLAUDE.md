# WorkflowX — AI Developer Context

## What This Is
WorkflowX is a workflow intelligence system. It reads events from screen capture tools
(Screenpipe, ActivityWatch), clusters them into workflow sessions, uses LLMs to infer
what the user was trying to do, diagnoses friction, generates replacement workflows
(connected to Agenticom for execution), and measures whether replacements actually work.
A background daemon runs the full pipeline automatically on a smart schedule.

## Repository Structure
```
src/workflowx/
├── models.py           # Core Pydantic domain models (the contract)
├── config.py           # Config from env vars / .env
├── storage.py          # Local JSON storage (file-per-day, patterns, outcomes)
├── export.py           # JSON/CSV export for external analysis
├── measurement.py      # Before/after ROI tracking
├── dashboard.py        # HTML ROI dashboard (static snapshot + live server mode)
├── server.py           # Live dashboard HTTP server (GET / and GET /api/data)
├── daemon.py           # Background scheduler — all pipeline stages, smart cadences
├── notifications.py    # macOS native notifications via osascript
├── mcp_server.py       # MCP server for Claude/Cursor integration
├── capture/            # Adapters for data sources
│   ├── screenpipe.py   # Reads Screenpipe's SQLite DB
│   └── activitywatch.py # Reads ActivityWatch REST API
├── inference/          # The intelligence layer
│   ├── clusterer.py    # Groups raw events into workflow sessions
│   ├── intent.py       # LLM-based intent inference + classification questions
│   ├── reporter.py     # Daily/weekly report generation
│   └── patterns.py     # Cross-day pattern detection + friction trends
├── replacement/        # Workflow replacement engine
│   └── engine.py       # LLM-powered proposals + Agenticom YAML
├── api/                # FastAPI endpoints (Phase 4)
└── cli/                # Click CLI — 16 commands
    └── main.py
```

## CLI Commands (16 total)
```bash
workflowx status      # Connection status, storage stats
workflowx capture     # Read events from Screenpipe/ActivityWatch
workflowx analyze     # LLM intent inference on sessions
workflowx validate    # Answer classification questions
workflowx report      # Daily/weekly workflow report
workflowx propose     # Generate replacement proposals

# Phase 2
workflowx patterns    # Detect recurring high-friction workflows
workflowx trends      # Weekly friction trajectory
workflowx export      # JSON/CSV export
workflowx mcp         # Start MCP server for Claude/Cursor

# Phase 3
workflowx adopt       # Mark a replacement as adopted, start ROI tracking
workflowx measure     # Measure actual ROI of adopted replacements
workflowx dashboard   # Generate static HTML ROI dashboard
workflowx serve       # Live dashboard server at localhost:7788 (Update button)
workflowx demo        # Full pipeline on synthetic data (no Screenpipe needed)

# Daemon
workflowx daemon start   # Install launchd agent + start (auto-restarts on login)
workflowx daemon stop    # Stop daemon + remove launchd plist
workflowx daemon status  # Job history table + upcoming schedule
workflowx daemon run     # Internal: raw event loop (called by launchd)
```

## Daemon Schedule
```
health:  every 5 min        — Screenpipe liveness; notifies if frames drop
capture: 12:55·17:55·22:55  — rolls up last 4h of Screenpipe events (every day)
analyze: 13:00·18:00·23:00  — LLM inference; event-triggers propose on HIGH/CRITICAL
measure: 07:00 daily        — adaptive ROI (weekly ≤30 days, monthly after)
brief:   08:30 weekdays     — morning notification: friction summary + pending actions
```

State: `~/.workflowx/daemon_state.json`
PID:   `~/.workflowx/daemon.pid`
Log:   `~/.workflowx/daemon.log`

## Common Dev Commands
```bash
make install-dev      # Install with all deps + dev tools
make test             # Run all tests with coverage
make test-fast        # Run unit tests only, stop on first failure
make lint             # Ruff + mypy
make format           # Auto-format
make check            # lint + test (run before PR)
```

## Architecture Principles
1. **Don't build capture** — use Screenpipe/ActivityWatch. Our value is intelligence.
2. **Local-first** — all data stays on device. No cloud requirement.
3. **Models are the contract** — everything flows through Pydantic models in models.py
4. **LLM calls are isolated** — only intent.py and engine.py call LLMs
5. **Daemon logic is pure** — scheduling/trigger functions (next_fire_time, should_measure,
   should_propose) have zero I/O and are 100% unit-testable without asyncio or mocking
6. **Measure everything** — without before/after ROI, we're just another advice tool

## Testing
- 134 tests in `tests/unit/` — fast, no external deps, no LLM calls
- `tests/integration/` — may require Screenpipe DB or LLM API key
- Always run `make test-fast` before committing
- Test files: test_models, test_clusterer, test_config, test_storage, test_storage_v2,
  test_reporter, test_patterns, test_measurement, test_export, test_dashboard, test_daemon

## Key Design Decisions
- **Screenpipe as primary capture**: MIT licensed, 12.6k stars, cross-platform
- **Session gap = 5 min**: Configurable. >5 min between events = new session
- **Friction = context switches / minute**: Simple heuristic, validated by user feedback
- **Classification questions**: When inference confidence < 0.7, ask ONE question
- **Agenticom integration**: Replacement engine generates workflow YAML
- **Pattern detection**: Greedy clustering by intent similarity (SequenceMatcher ≥ 0.55)
- **ROI measurement**: Compare pre-adoption vs post-adoption weekly minutes for same intent
- **MCP server**: 5 tools (sessions, friction, patterns, trends, roi) via FastMCP
- **Daemon scheduling**: next_fire_time() scans 8 days forward; weekdays_only=True for
  brief, False for capture/analyze (late-night work happens on weekends too)
- **Adaptive measure cadence**: weeks_tracked < expected; weekly ≤30d, monthly >30d
- **Propose dedup**: per session ID, pruned after 30 days

## PR Workflow
1. Branch from `main`
2. `make check` must pass
3. Add tests for new logic
4. Atomic commits: one concern per commit
