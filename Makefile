.PHONY: install install-dev test lint format check clean

install:
	pip install -e ".[all]"

install-dev:
	pip install -e ".[all,dev]"
	pre-commit install

test:
	pytest tests/ -v --cov=workflowx --cov-report=term-missing

test-fast:
	pytest tests/unit/ -v -x

lint:
	ruff check src/ tests/
	mypy src/workflowx/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

check: lint test

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
