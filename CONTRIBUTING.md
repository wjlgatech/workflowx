# Contributing to WorkflowX

We welcome contributions. Here's how to get started fast.

## Setup (2 minutes)

```bash
git clone https://github.com/wjlgatech/workflowx.git
cd workflowx
python -m venv .venv && source .venv/bin/activate
make install-dev
make test
```

If tests pass, you're ready.

## What to Work On

Check [Issues](https://github.com/wjlgatech/workflowx/issues) for tasks tagged:
- `good-first-issue` — small, well-scoped, great for first contribution
- `help-wanted` — we need your help here
- `capture-adapter` — new data source adapters (ActivityWatch, WakaTime, etc.)
- `inference` — improving intent inference accuracy
- `replacement` — workflow replacement engine work

## How to Contribute

### 1. Pick an issue or propose one
Comment on an issue to claim it, or open a new one describing what you want to build.

### 2. Branch and build
```bash
git checkout -b your-feature
# write code
make check   # must pass
```

### 3. Submit a PR
- Keep PRs focused (one concern per PR)
- Add tests for new logic
- Update CLAUDE.md if you change architecture

### 4. Review
We review PRs within 48 hours. Expect direct, constructive feedback.

## Code Style

- Python 3.10+, type hints everywhere
- Pydantic models for data contracts
- structlog for logging
- Ruff for linting + formatting
- Tests in `tests/unit/` (fast) or `tests/integration/` (external deps)

## Architecture Rules

1. **Capture adapters are thin** — they convert external data to `RawEvent`. No business logic.
2. **Models are the contract** — if you need a new data shape, add it to `models.py` first.
3. **LLM calls are isolated** — only `inference/intent.py` talks to LLMs. Everything else is deterministic.
4. **Privacy by default** — no data leaves the device. No cloud calls except explicit LLM inference.

## Adding a New Capture Adapter

Want to add support for ActivityWatch, WakaTime, or another tool?

1. Create `src/workflowx/capture/your_source.py`
2. Implement a class with `read_events(since, until, limit) -> list[RawEvent]`
3. Add tests in `tests/unit/test_your_source.py`
4. Add optional deps to `pyproject.toml` under `[project.optional-dependencies]`

That's it. The inference layer doesn't care where events come from.

## Questions?

Open an issue or reach out to [@wjlgatech](https://github.com/wjlgatech).
