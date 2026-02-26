# WorkflowX — AI Developer Context

## What This Is
WorkflowX is a workflow intelligence system. It reads events from screen capture tools
(Screenpipe, ActivityWatch), clusters them into workflow sessions, uses LLMs to infer
what the user was trying to do, diagnoses friction, and generates replacement workflows
(connected to Agenticom for execution).

## Repository Structure
```
src/workflowx/
├── models.py           # Core Pydantic domain models
├── capture/            # Adapters for data sources (Screenpipe, ActivityWatch)
│   └── screenpipe.py   # Reads Screenpipe's SQLite DB
├── inference/          # The intelligence layer
│   ├── clusterer.py    # Groups raw events into workflow sessions
│   └── intent.py       # LLM-based intent inference + classification questions
├── replacement/        # Workflow replacement engine (connects to Agenticom)
├── api/                # FastAPI endpoints
└── cli/                # Click CLI (primary user interface)
    └── main.py
```

## Common Commands
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
4. **LLM calls are isolated** — inference/intent.py is the only file that calls LLMs
5. **CLI-first UX** — dashboard comes later. CLI is the primary interface.

## Testing
- `tests/unit/` — fast, no external deps, no LLM calls
- `tests/integration/` — may require Screenpipe DB or LLM API key
- Always run `make test-fast` before committing

## Key Design Decisions
- **Screenpipe as primary capture**: MIT licensed, 12.6k stars, MCP server, cross-platform
- **Session gap = 5 min**: Configurable. >5 min between events = new session
- **Friction = context switches / minute**: Simple heuristic, validated by user feedback
- **Classification questions**: When inference confidence < 0.7, ask ONE question
- **Agenticom integration**: Replacement engine generates workflow YAML for Agenticom CLI

## PR Workflow
1. Branch from `main`
2. `make check` must pass
3. Add tests for new logic
4. Atomic commits: one concern per commit
