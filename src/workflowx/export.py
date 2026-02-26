"""Export module — JSON and CSV export for external analysis.

When your data lives in your own files, you should be able to take it
anywhere. Pipe it into a Jupyter notebook, a spreadsheet, a BI tool.
No lock-in. No API tax.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

import structlog

from workflowx.models import (
    FrictionTrend,
    WorkflowPattern,
    WorkflowSession,
)

logger = structlog.get_logger()


def sessions_to_json(sessions: Sequence[WorkflowSession]) -> str:
    """Export sessions as a JSON array string."""
    data = [json.loads(s.model_dump_json()) for s in sessions]
    # Strip events for cleaner export (they're verbose)
    for d in data:
        d.pop("events", None)
    return json.dumps(data, indent=2, default=str)


def sessions_to_csv(sessions: Sequence[WorkflowSession]) -> str:
    """Export sessions as CSV string.

    Flat structure: one row per session. Apps are comma-joined in a single cell.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "id",
        "start_time",
        "end_time",
        "duration_minutes",
        "apps",
        "context_switches",
        "friction_level",
        "inferred_intent",
        "confidence",
        "friction_details",
        "user_validated",
        "user_label",
    ])

    for s in sessions:
        writer.writerow([
            s.id,
            s.start_time.isoformat(),
            s.end_time.isoformat(),
            f"{s.total_duration_minutes:.1f}",
            "|".join(s.apps_used),
            s.context_switches,
            s.friction_level.value,
            s.inferred_intent,
            f"{s.confidence:.2f}",
            s.friction_details,
            s.user_validated,
            s.user_label,
        ])

    return output.getvalue()


def patterns_to_json(patterns: Sequence[WorkflowPattern]) -> str:
    """Export patterns as JSON array."""
    data = [json.loads(p.model_dump_json()) for p in patterns]
    return json.dumps(data, indent=2, default=str)


def patterns_to_csv(patterns: Sequence[WorkflowPattern]) -> str:
    """Export patterns as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "id",
        "intent",
        "occurrences",
        "avg_duration_minutes",
        "total_time_invested_minutes",
        "most_common_friction",
        "avg_context_switches",
        "trend",
        "apps_involved",
        "first_seen",
        "last_seen",
    ])

    for p in patterns:
        writer.writerow([
            p.id,
            p.intent,
            p.occurrences,
            f"{p.avg_duration_minutes:.1f}",
            f"{p.total_time_invested_minutes:.1f}",
            p.most_common_friction.value,
            f"{p.avg_context_switches:.1f}",
            p.trend,
            "|".join(p.apps_involved),
            p.first_seen.isoformat(),
            p.last_seen.isoformat(),
        ])

    return output.getvalue()


def trends_to_json(trends: Sequence[FrictionTrend]) -> str:
    """Export trends as JSON array."""
    data = [json.loads(t.model_dump_json()) for t in trends]
    return json.dumps(data, indent=2, default=str)


def trends_to_csv(trends: Sequence[FrictionTrend]) -> str:
    """Export trends as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "week_label",
        "total_sessions",
        "total_minutes",
        "high_friction_minutes",
        "high_friction_ratio",
        "avg_switches_per_session",
        "top_friction_intents",
    ])

    for t in trends:
        writer.writerow([
            t.week_label,
            t.total_sessions,
            f"{t.total_minutes:.1f}",
            f"{t.high_friction_minutes:.1f}",
            f"{t.high_friction_ratio:.3f}",
            f"{t.avg_switches_per_session:.1f}",
            "|".join(t.top_friction_intents),
        ])

    return output.getvalue()


def export_to_file(content: str, path: Path) -> Path:
    """Write export content to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    logger.info("exported", path=str(path), size=len(content))
    return path
