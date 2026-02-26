"""Before/after measurement — tracks whether replacements actually work.

This is the truth machine. Every productivity tool promises savings.
Almost none measure whether those savings materialized. WorkflowX does.

The loop:
1. User adopts a replacement proposal
2. We continue observing the same intent pattern
3. We compare pre-adoption vs post-adoption duration
4. We report actual (not estimated) ROI

Without this, WorkflowX is just another advice engine.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Sequence

import structlog

from workflowx.models import (
    FrictionLevel,
    ReplacementOutcome,
    ReplacementProposal,
    WorkflowPattern,
    WorkflowSession,
)

logger = structlog.get_logger()


def _make_outcome_id(proposal_id: str) -> str:
    return "out_" + hashlib.md5(proposal_id.encode()).hexdigest()[:12]


def create_outcome(
    proposal: ReplacementProposal,
    before_minutes_per_week: float,
) -> ReplacementOutcome:
    """Create a new outcome tracker when a user adopts a replacement."""
    return ReplacementOutcome(
        id=_make_outcome_id(proposal.diagnosis_id),
        proposal_id=proposal.diagnosis_id,
        intent=proposal.original_workflow.split("(")[0].strip(),
        adopted=True,
        adopted_date=datetime.now(),
        before_minutes_per_week=before_minutes_per_week,
        after_minutes_per_week=0.0,
        actual_savings_minutes=0.0,
        cumulative_savings_minutes=0.0,
        weeks_tracked=0,
        status="measuring",
    )


def measure_outcome(
    outcome: ReplacementOutcome,
    recent_sessions: Sequence[WorkflowSession],
    lookback_days: int = 7,
) -> ReplacementOutcome:
    """Measure actual time spent on the replaced workflow intent.

    Scans recent sessions for the same intent. If time decreased vs baseline,
    the replacement is working. If not, it isn't — and we say so.
    """
    # Find sessions matching this outcome's intent (fuzzy match)
    from workflowx.inference.patterns import _intent_similarity

    matching_minutes = 0.0
    match_count = 0

    cutoff = datetime.now() - timedelta(days=lookback_days)
    for session in recent_sessions:
        if session.start_time < cutoff:
            continue
        if _intent_similarity(session.inferred_intent, outcome.intent) > 0.5:
            matching_minutes += session.total_duration_minutes
            match_count += 1

    # Scale to weekly estimate
    weeks_factor = lookback_days / 7.0
    weekly_minutes = matching_minutes / weeks_factor if weeks_factor > 0 else matching_minutes

    # Update outcome
    outcome.after_minutes_per_week = round(weekly_minutes, 1)
    outcome.actual_savings_minutes = round(
        outcome.before_minutes_per_week - outcome.after_minutes_per_week, 1
    )
    outcome.weeks_tracked += 1
    outcome.cumulative_savings_minutes = round(
        outcome.actual_savings_minutes * outcome.weeks_tracked, 1
    )

    # Determine status
    if outcome.actual_savings_minutes > 0:
        outcome.status = "adopted"  # It's working
    elif outcome.weeks_tracked >= 2 and outcome.actual_savings_minutes <= 0:
        outcome.status = "rejected"  # Tried it, didn't help
    else:
        outcome.status = "measuring"  # Still gathering data

    logger.info(
        "outcome_measured",
        intent=outcome.intent,
        before=outcome.before_minutes_per_week,
        after=outcome.after_minutes_per_week,
        savings=outcome.actual_savings_minutes,
        status=outcome.status,
    )
    return outcome


def compute_roi_summary(outcomes: Sequence[ReplacementOutcome]) -> dict:
    """Compute aggregate ROI metrics across all tracked outcomes.

    Returns a dict with everything the ROI dashboard needs.
    """
    adopted = [o for o in outcomes if o.status == "adopted"]
    rejected = [o for o in outcomes if o.status == "rejected"]
    measuring = [o for o in outcomes if o.status == "measuring"]

    total_weekly_savings = sum(o.actual_savings_minutes for o in adopted)
    total_cumulative_savings = sum(o.cumulative_savings_minutes for o in adopted)

    return {
        "total_outcomes": len(outcomes),
        "adopted": len(adopted),
        "rejected": len(rejected),
        "measuring": len(measuring),
        "adoption_rate": len(adopted) / len(outcomes) if outcomes else 0.0,
        "total_weekly_savings_minutes": round(total_weekly_savings, 1),
        "total_weekly_savings_hours": round(total_weekly_savings / 60.0, 2),
        "total_cumulative_savings_minutes": round(total_cumulative_savings, 1),
        "total_cumulative_savings_hours": round(total_cumulative_savings / 60.0, 2),
        "outcomes": [
            {
                "intent": o.intent,
                "before": o.before_minutes_per_week,
                "after": o.after_minutes_per_week,
                "savings": o.actual_savings_minutes,
                "cumulative": o.cumulative_savings_minutes,
                "weeks": o.weeks_tracked,
                "status": o.status,
            }
            for o in outcomes
        ],
    }


def format_roi_report(
    outcomes: Sequence[ReplacementOutcome],
    hourly_rate: float = 75.0,
) -> str:
    """Format ROI data as readable text."""
    if not outcomes:
        return "No replacement outcomes tracked yet. Adopt a proposal to start measuring."

    summary = compute_roi_summary(outcomes)
    weekly_usd = summary["total_weekly_savings_hours"] * hourly_rate
    cumul_usd = summary["total_cumulative_savings_hours"] * hourly_rate

    lines = [
        f"{'='*60}",
        "  ROI DASHBOARD",
        f"{'='*60}",
        "",
        f"  Replacements tracked: {summary['total_outcomes']}",
        f"  Adopted: {summary['adopted']} | Rejected: {summary['rejected']} | Measuring: {summary['measuring']}",
        f"  Adoption rate: {summary['adoption_rate']:.0%}",
        "",
        f"  WEEKLY SAVINGS",
        f"  Time: {summary['total_weekly_savings_minutes']:.0f} min/week ({summary['total_weekly_savings_hours']:.1f} hrs)",
        f"  Value: ${weekly_usd:.0f}/week",
        "",
        f"  CUMULATIVE SAVINGS",
        f"  Time: {summary['total_cumulative_savings_minutes']:.0f} min ({summary['total_cumulative_savings_hours']:.1f} hrs)",
        f"  Value: ${cumul_usd:.0f}",
        "",
    ]

    if summary["outcomes"]:
        lines.append("  BREAKDOWN")
        lines.append(f"  {'─'*50}")
        for o in summary["outcomes"]:
            status_icon = {"adopted": "✓", "rejected": "✗", "measuring": "⏳"}.get(
                o["status"], "?"
            )
            lines.append(
                f"  {status_icon} {o['intent'][:35]:35s} "
                f"{o['before']:.0f}→{o['after']:.0f}min "
                f"({o['savings']:+.0f}min/wk) "
                f"[{o['weeks']}wk]"
            )
        lines.append("")

    return "\n".join(lines)
