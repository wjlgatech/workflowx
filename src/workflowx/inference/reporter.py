"""Daily and weekly workflow report generator.

Takes analyzed sessions and produces human-readable reports.
This is what the user sees every day — it must be clear, actionable, and honest.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Sequence

import structlog

from workflowx.models import (
    FrictionLevel,
    WeeklyReport,
    WorkflowDiagnosis,
    WorkflowSession,
)
from workflowx.inference.intent import diagnose_workflow

logger = structlog.get_logger()


def generate_daily_report(
    sessions: list[WorkflowSession],
    hourly_rate_usd: float = 75.0,
) -> str:
    """Generate a plain-text daily workflow report.

    Not a dashboard. Not a pie chart. A clear answer to:
    "Where did my time go, and what should I change?"
    """
    if not sessions:
        return "No workflow sessions recorded today."

    total_min = sum(s.total_duration_minutes for s in sessions)
    total_switches = sum(s.context_switches for s in sessions)

    # Separate by friction level
    high_friction = [
        s for s in sessions
        if s.friction_level in (FrictionLevel.HIGH, FrictionLevel.CRITICAL)
    ]
    low_friction = [
        s for s in sessions
        if s.friction_level in (FrictionLevel.LOW, FrictionLevel.MEDIUM)
    ]

    high_friction_min = sum(s.total_duration_minutes for s in high_friction)
    high_friction_cost = (high_friction_min / 60.0) * hourly_rate_usd

    lines = [
        f"{'='*60}",
        f"  DAILY WORKFLOW REPORT — {date.today().isoformat()}",
        f"{'='*60}",
        "",
        f"  Sessions: {len(sessions)}",
        f"  Total time tracked: {total_min:.0f} min ({total_min/60:.1f} hrs)",
        f"  Context switches: {total_switches}",
        "",
    ]

    if high_friction:
        lines.extend([
            f"  !! HIGH-FRICTION SESSIONS: {len(high_friction)}",
            f"     Time in friction: {high_friction_min:.0f} min",
            f"     Estimated cost: ${high_friction_cost:.0f}",
            "",
        ])

    # Top sessions by duration
    lines.append("  TOP SESSIONS (by duration)")
    lines.append(f"  {'-'*54}")

    sorted_sessions = sorted(sessions, key=lambda s: s.total_duration_minutes, reverse=True)
    for i, s in enumerate(sorted_sessions[:8], 1):
        intent = s.inferred_intent or "(not yet analyzed)"
        friction_marker = " !!" if s.friction_level.value in ("high", "critical") else ""

        lines.append(
            f"  {i}. [{s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}] "
            f"{s.total_duration_minutes:.0f}min | {', '.join(s.apps_used[:3])}"
            f"{friction_marker}"
        )
        if s.inferred_intent:
            lines.append(f"     Intent: {intent} (conf: {s.confidence:.0%})")
        if s.friction_details:
            lines.append(f"     Friction: {s.friction_details[:80]}")
        lines.append("")

    # Actionable insight
    if high_friction:
        lines.extend([
            f"  {'='*54}",
            f"  ACTION: {len(high_friction)} sessions had high friction.",
            f"  Run 'workflowx validate' to confirm what these were,",
            f"  then 'workflowx propose' to see replacement options.",
            f"  {'='*54}",
        ])
    else:
        lines.extend([
            f"  {'='*54}",
            "  All sessions had low friction today. Nice.",
            f"  {'='*54}",
        ])

    return "\n".join(lines)


def generate_weekly_report(
    sessions: list[WorkflowSession],
    hourly_rate_usd: float = 75.0,
) -> WeeklyReport:
    """Generate a structured weekly report with diagnoses.

    This is the data structure that feeds the replacement engine.
    """
    if not sessions:
        now = datetime.now()
        return WeeklyReport(
            week_start=now - timedelta(days=7),
            week_end=now,
        )

    sorted_sessions = sorted(sessions, key=lambda s: s.start_time)
    week_start = sorted_sessions[0].start_time
    week_end = sorted_sessions[-1].end_time

    # Diagnose all sessions
    diagnoses = [
        diagnose_workflow(s, hourly_rate_usd=hourly_rate_usd)
        for s in sessions
    ]

    # Top friction points: sessions with highest automation potential
    top_friction = sorted(
        diagnoses,
        key=lambda d: d.automation_potential * d.total_time_minutes,
        reverse=True,
    )[:5]

    # Top workflows by time
    top_workflows = sorted(
        sessions,
        key=lambda s: s.total_duration_minutes,
        reverse=True,
    )[:10]

    total_hours = sum(s.total_duration_minutes for s in sessions) / 60.0
    total_savings = sum(
        d.total_time_minutes * d.automation_potential
        for d in top_friction
    )

    return WeeklyReport(
        week_start=week_start,
        week_end=week_end,
        total_sessions=len(sessions),
        total_hours_tracked=round(total_hours, 1),
        top_workflows=top_workflows,
        top_friction_points=top_friction,
        total_estimated_savings_minutes=round(total_savings, 0),
    )


def format_weekly_summary(report: WeeklyReport, hourly_rate: float = 75.0) -> str:
    """Format a weekly report as readable text."""
    savings_hours = report.total_estimated_savings_minutes / 60.0
    savings_usd = savings_hours * hourly_rate

    lines = [
        f"{'='*60}",
        f"  WEEKLY WORKFLOW REPORT",
        f"  {report.week_start.strftime('%b %d')} — {report.week_end.strftime('%b %d, %Y')}",
        f"{'='*60}",
        "",
        f"  Sessions: {report.total_sessions}",
        f"  Hours tracked: {report.total_hours_tracked:.1f}",
        "",
        f"  POTENTIAL SAVINGS",
        f"  Time: {report.total_estimated_savings_minutes:.0f} min/week ({savings_hours:.1f} hrs)",
        f"  Value: ${savings_usd:.0f}/week (at ${hourly_rate:.0f}/hr)",
        "",
    ]

    if report.top_friction_points:
        lines.append("  TOP FRICTION POINTS (automation candidates)")
        lines.append(f"  {'-'*50}")
        for i, d in enumerate(report.top_friction_points, 1):
            lines.append(
                f"  {i}. {d.intent or 'unknown'} — "
                f"{d.total_time_minutes:.0f}min, "
                f"{d.automation_potential:.0%} automatable"
            )
        lines.append("")

    lines.extend([
        f"  {'='*50}",
        f"  Run 'workflowx propose' to see replacement workflows.",
        f"  {'='*50}",
    ])

    return "\n".join(lines)
