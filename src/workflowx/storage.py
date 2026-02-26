"""Local JSON storage for WorkflowX data.

Simple, file-based, no external dependencies. Privacy by construction.
Each day's data is a separate JSON file in ~/.workflowx/
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from workflowx.models import (
    ClassificationQuestion,
    ReplacementOutcome,
    WeeklyReport,
    WorkflowDiagnosis,
    WorkflowPattern,
    WorkflowSession,
)

logger = structlog.get_logger()


class LocalStore:
    """File-based storage for workflow data. One JSON file per day."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir = self.data_dir / "sessions"
        self.sessions_dir.mkdir(exist_ok=True)
        self.questions_dir = self.data_dir / "questions"
        self.questions_dir.mkdir(exist_ok=True)
        self.reports_dir = self.data_dir / "reports"
        self.reports_dir.mkdir(exist_ok=True)
        self.patterns_dir = self.data_dir / "patterns"
        self.patterns_dir.mkdir(exist_ok=True)
        self.outcomes_dir = self.data_dir / "outcomes"
        self.outcomes_dir.mkdir(exist_ok=True)

    def _date_path(self, base_dir: Path, d: date) -> Path:
        return base_dir / f"{d.isoformat()}.json"

    # ── Sessions ──────────────────────────────────────────────

    def save_sessions(self, sessions: list[WorkflowSession], d: date | None = None) -> Path:
        """Save sessions for a given day."""
        d = d or date.today()
        path = self._date_path(self.sessions_dir, d)

        existing = self._load_json_list(path)
        existing_ids = {s.get("id") for s in existing}

        for session in sessions:
            data = json.loads(session.model_dump_json())
            if session.id not in existing_ids:
                existing.append(data)
                existing_ids.add(session.id)
            else:
                # Update existing session (e.g., after intent inference)
                existing = [
                    data if s.get("id") == session.id else s
                    for s in existing
                ]

        self._save_json(path, existing)
        logger.info("sessions_saved", count=len(sessions), path=str(path))
        return path

    def load_sessions(self, d: date | None = None) -> list[WorkflowSession]:
        """Load sessions for a given day."""
        d = d or date.today()
        path = self._date_path(self.sessions_dir, d)
        raw = self._load_json_list(path)
        return [WorkflowSession.model_validate(s) for s in raw]

    def load_sessions_range(self, start: date, end: date) -> list[WorkflowSession]:
        """Load sessions across a date range (inclusive)."""
        sessions = []
        current = start
        while current <= end:
            sessions.extend(self.load_sessions(current))
            current += timedelta(days=1)
        return sessions

    # ── Classification Questions ──────────────────────────────

    def save_questions(self, questions: list[ClassificationQuestion]) -> Path:
        """Save pending classification questions."""
        path = self.questions_dir / "pending.json"
        existing = self._load_json_list(path)
        existing_ids = {q.get("session_id") for q in existing}

        for q in questions:
            data = json.loads(q.model_dump_json())
            if q.session_id not in existing_ids:
                existing.append(data)

        self._save_json(path, existing)
        return path

    def load_pending_questions(self) -> list[ClassificationQuestion]:
        """Load unanswered classification questions."""
        path = self.questions_dir / "pending.json"
        raw = self._load_json_list(path)
        return [
            ClassificationQuestion.model_validate(q)
            for q in raw
            if not q.get("answered", False)
        ]

    def answer_question(self, session_id: str, answer: str) -> None:
        """Record a user's answer to a classification question."""
        path = self.questions_dir / "pending.json"
        raw = self._load_json_list(path)

        for q in raw:
            if q.get("session_id") == session_id:
                q["answer"] = answer
                q["answered"] = True

        self._save_json(path, raw)

    # ── Reports ───────────────────────────────────────────────

    def save_report(self, report: WeeklyReport) -> Path:
        """Save a weekly report."""
        d = report.week_start.date() if isinstance(report.week_start, datetime) else report.week_start
        path = self.reports_dir / f"week-{d.isoformat()}.json"
        data = json.loads(report.model_dump_json())
        self._save_json(path, data)
        return path

    # ── Patterns (Phase 2) ────────────────────────────────────

    def save_patterns(self, patterns: list[WorkflowPattern]) -> Path:
        """Save detected patterns."""
        path = self.patterns_dir / "latest.json"
        data = [json.loads(p.model_dump_json()) for p in patterns]
        self._save_json(path, data)
        logger.info("patterns_saved", count=len(patterns))
        return path

    def load_patterns(self) -> list[WorkflowPattern]:
        """Load latest detected patterns."""
        path = self.patterns_dir / "latest.json"
        raw = self._load_json_list(path)
        return [WorkflowPattern.model_validate(p) for p in raw]

    # ── Replacement Outcomes (Phase 3) ────────────────────────

    def save_outcomes(self, outcomes: list[ReplacementOutcome]) -> Path:
        """Save replacement outcomes."""
        path = self.outcomes_dir / "outcomes.json"
        existing = self._load_json_list(path)
        existing_ids = {o.get("id") for o in existing}

        for outcome in outcomes:
            data = json.loads(outcome.model_dump_json())
            if outcome.id not in existing_ids:
                existing.append(data)
                existing_ids.add(outcome.id)
            else:
                existing = [
                    data if o.get("id") == outcome.id else o
                    for o in existing
                ]

        self._save_json(path, existing)
        logger.info("outcomes_saved", count=len(outcomes))
        return path

    def load_outcomes(self) -> list[ReplacementOutcome]:
        """Load all replacement outcomes."""
        path = self.outcomes_dir / "outcomes.json"
        raw = self._load_json_list(path)
        return [ReplacementOutcome.model_validate(o) for o in raw]

    def save_outcome(self, outcome: ReplacementOutcome) -> Path:
        """Save or update a single outcome."""
        return self.save_outcomes([outcome])

    # ── Helpers ────────────────────────────────────────────────

    def _load_json_list(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _save_json(self, path: Path, data: Any) -> None:
        path.write_text(json.dumps(data, indent=2, default=str))
