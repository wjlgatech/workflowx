# WorkflowX — AI Developer Context

## What This Is
WorkflowX is a workflow intelligence system. It reads events from screen capture tools
(Screenpipe, ActivityWatch), clusters them into workflow sessions, uses LLMs to infer
what the user was trying to do, diagnoses friction, generates replacement workflows
(connected to Agenticom for execution), and measures whether replacements actually work.

## Repository Structure
```
src/workflowx/
├── models.py           # 11 Pydantic domain models (the contract)
├── config.py           # Config from env vars / .env
├── storage.py          # Local JSON storage (file-per-day, patterns, outcomes)
├── export.py           # JSON/CSV export for external analysis
├── measurement.py      # Before/after ROI tracking
├── dashboard.py        # Self-contained HTML ROI dashboard (Chart.js)
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
└── cli/                # Click CLI — 12 commands
    └── main.py
```

## CLI Commands (12 total)
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
workflowx dashboard   # Generate HTML ROI dashboard
```

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
5. **CLI-first UX** — dashboard is HTML export, not a server.
6. **Measure everything** — without before/after ROI, we're just another advice tool.

## Testing
- 63 tests in `tests/unit/` — fast, no external deps, no LLM calls
- `tests/integration/` — may require Screenpipe DB or LLM API key
- Always run `make test-fast` before committing
- Test files: test_models, test_clusterer, test_config, test_storage, test_storage_v2,
  test_reporter, test_patterns, test_measurement, test_export, test_dashboard

## Key Design Decisions
- **Screenpipe as primary capture**: MIT licensed, 12.6k stars, cross-platform
- **Session gap = 5 min**: Configurable. >5 min between events = new session
- **Friction = context switches / minute**: Simple heuristic, validated by user feedback
- **Classification questions**: When inference confidence < 0.7, ask ONE question
- **Agenticom integration**: Replacement engine generates workflow YAML
- **Pattern detection**: Greedy clustering by intent similarity (SequenceMatcher ≥ 0.55)
- **ROI measurement**: Compare pre-adoption vs post-adoption weekly minutes for same intent
- **MCP server**: 5 tools (sessions, friction, patterns, trends, roi) via FastMCP

## PR Workflow
1. Branch from `main`
2. `make check` must pass
3. Add tests for new logic
4. Atomic commits: one concern per commit
