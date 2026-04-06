"""Pattern detection — finds recurring high-friction workflows across days.

Imagine you're a detective looking at a suspect's routine. You don't care about
the one time they went to the library. You care about the pattern: every Tuesday
and Thursday at 2pm, they spend 50 minutes doing the same high-friction task.

That's what this module does. It scans sessions across days, groups by intent
similarity, and surfaces the ones that keep bleeding your time.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Sequence

import structlog

from workflowx.models import (
    FrictionLevel,
    FrictionTrend,
    WorkflowPattern,
    WorkflowSession,
)

logger = structlog.get_logger()

# ── Intent Similarity ────────────────────────────────────────

# Two sessions are "the same pattern" if their intents are similar enough.
# "competitive research" and "competitor analysis" should group together.
SIMILARITY_THRESHOLD = 0.55


def _intent_similarity(a: str, b: str) -> float:
    """Compute normalized similarity between two intent strings.

    Uses SequenceMatcher on lowercased, stripped tokens. Fast enough for
    hundreds of sessions — no need for embeddings at this scale.
    """
    if not a or not b:
        return 0.0
    a_clean = a.lower().strip()
    b_clean = b.lower().strip()
    if a_clean == b_clean:
        return 1.0
    return SequenceMatcher(None, a_clean, b_clean).ratio()


def _make_pattern_id(intent: str) -> str:
    """Deterministic pattern ID from the canonical intent string."""
    return "pat_" + hashlib.md5(intent.lower().strip().encode()).hexdigest()[:12]


# ── Pattern Detection ────────────────────────────────────────


def detect_patterns(
    sessions: Sequence[WorkflowSession],
    similarity_threshold: float = SIMILARITY_THRESHOLD,
    min_occurrences: int = 2,
) -> list[WorkflowPattern]:
    """Detect recurring workflow patterns from sessions across multiple days.

    Algorithm:
    1. Filter to sessions with inferred intents.
    2. Group sessions by intent similarity (greedy clustering).
    3. For each group with >= min_occurrences, build a WorkflowPattern.
    4. Score trend (improving/worsening/stable) based on friction trajectory.

    Returns patterns sorted by total_time_invested descending — the ones
    costing you the most are at the top.
    """
    analyzed = [s for s in sessions if s.inferred_intent and s.inferred_intent != "inference_failed"]
    if not analyzed:
        return []

    # Greedy clustering by intent similarity
    clusters: list[list[WorkflowSession]] = []
    assigned: set[str] = set()

    # Sort by time so the first occurrence becomes the canonical intent
    sorted_sessions = sorted(analyzed, key=lambda s: s.start_time)

    for session in sorted_sessions:
        if session.id in assigned:
            continue

        # Find or create cluster
        best_cluster = None
        best_sim = 0.0

        for cluster in clusters:
            # Compare against the cluster's canonical intent (first session)
            sim = _intent_similarity(session.inferred_intent, cluster[0].inferred_intent)
            if sim > best_sim and sim >= similarity_threshold:
                best_sim = sim
                best_cluster = cluster

        if best_cluster is not None:
            best_cluster.append(session)
        else:
            clusters.append([session])

        assigned.add(session.id)

    # Build patterns from clusters
    patterns = []
    for cluster in clusters:
        if len(cluster) < min_occurrences:
            continue

        canonical_intent = cluster[0].inferred_intent
        pattern = _build_pattern(canonical_intent, cluster)
        patterns.append(pattern)

    # Sort by total time invested (biggest time sinks first)
    patterns.sort(key=lambda p: p.total_time_invested_minutes, reverse=True)

    logger.info(
        "patterns_detected",
        total_sessions=len(analyzed),
        patterns_found=len(patterns),
    )
    return patterns


def _build_pattern(intent: str, sessions: list[WorkflowSession]) -> WorkflowPattern:
    """Build a WorkflowPattern from a cluster of similar sessions."""
    sorted_sessions = sorted(sessions, key=lambda s: s.start_time)

    total_minutes = sum(s.total_duration_minutes for s in sessions)
    avg_minutes = total_minutes / len(sessions)
    avg_switches = sum(s.context_switches for s in sessions) / len(sessions)

    # Most common friction level
    friction_counts = Counter(s.friction_level for s in sessions)
    most_common_friction = friction_counts.most_common(1)[0][0]

    # All apps involved
    all_apps: list[str] = []
    seen_apps: set[str] = set()
    for s in sessions:
        for app in s.apps_used:
            if app not in seen_apps:
                all_apps.append(app)
                seen_apps.add(app)

    # Trend: compare friction of first half vs second half
    mid = len(sorted_sessions) // 2
    if mid > 0 and len(sorted_sessions) > 2:
        first_half_friction = sum(
            _friction_score(s.friction_level) for s in sorted_sessions[:mid]
        ) / mid
        second_half_friction = sum(
            _friction_score(s.friction_level) for s in sorted_sessions[mid:]
        ) / (len(sorted_sessions) - mid)

        diff = second_half_friction - first_half_friction
        if diff > 0.3:
            trend = "worsening"
        elif diff < -0.3:
            trend = "improving"
        else:
            trend = "stable"
    else:
        trend = "stable"

    return WorkflowPattern(
        id=_make_pattern_id(intent),
        intent=intent,
        occurrences=len(sessions),
        first_seen=sorted_sessions[0].start_time,
        last_seen=sorted_sessions[-1].start_time,
        avg_duration_minutes=round(avg_minutes, 1),
        most_common_friction=most_common_friction,
        avg_context_switches=round(avg_switches, 1),
        session_ids=[s.id for s in sessions],
        trend=trend,
        total_time_invested_minutes=round(total_minutes, 1),
        apps_involved=all_apps[:10],
    )


def _friction_score(level: FrictionLevel) -> float:
    """Convert friction level to a numeric score for trend comparison."""
    return {
        FrictionLevel.LOW: 0.0,
        FrictionLevel.MEDIUM: 1.0,
        FrictionLevel.HIGH: 2.0,
        FrictionLevel.CRITICAL: 3.0,
    }.get(level, 0.0)


# ── Friction Trends ──────────────────────────────────────────


def compute_friction_trends(
    sessions: Sequence[WorkflowSession],
    num_weeks: int = 4,
) -> list[FrictionTrend]:
    """Compute weekly friction trends from sessions.

    Groups sessions by ISO week, then for each week computes:
    - Total sessions, total minutes
    - High-friction ratio (what % of your time was friction?)
    - Average context switches
    - Top friction intents

    Returns trends in chronological order (oldest first) so you can
    see the trajectory: are things getting better or worse?
    """
    if not sessions:
        return []

    # Group sessions by ISO week
    weeks: dict[str, list[WorkflowSession]] = defaultdict(list)
    for s in sessions:
        iso = s.start_time.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"
        weeks[week_label].append(s)

    # Sort weeks chronologically, take last num_weeks
    sorted_weeks = sorted(weeks.items(), key=lambda kv: kv[0])[-num_weeks:]

    trends = []
    for week_label, week_sessions in sorted_weeks:
        total_min = sum(s.total_duration_minutes for s in week_sessions)
        high_friction_min = sum(
            s.total_duration_minutes
            for s in week_sessions
            if s.friction_level in (FrictionLevel.HIGH, FrictionLevel.CRITICAL)
        )
        total_switches = sum(s.context_switches for s in week_sessions)
        avg_switches = total_switches / len(week_sessions) if week_sessions else 0.0

        # Top friction intents
        friction_intents = [
            s.inferred_intent
            for s in week_sessions
            if s.friction_level in (FrictionLevel.HIGH, FrictionLevel.CRITICAL)
            and s.inferred_intent
        ]
        top_intents = [
            intent for intent, _ in Counter(friction_intents).most_common(3)
        ]

        # Week start/end from actual session times
        sorted_s = sorted(week_sessions, key=lambda s: s.start_time)
        week_start = sorted_s[0].start_time
        week_end = sorted_s[-1].end_time

        trends.append(FrictionTrend(
            week_label=week_label,
            week_start=week_start,
            week_end=week_end,
            total_sessions=len(week_sessions),
            total_minutes=round(total_min, 1),
            high_friction_minutes=round(high_friction_min, 1),
            high_friction_ratio=round(high_friction_min / total_min, 3) if total_min > 0 else 0.0,
            avg_switches_per_session=round(avg_switches, 1),
            top_friction_intents=top_intents,
        ))

    logger.info(
        "friction_trends_computed",
        weeks=len(trends),
        latest_friction_ratio=trends[-1].high_friction_ratio if trends else 0,
    )
    return trends


def format_trends_report(trends: list[FrictionTrend]) -> str:
    """Format friction trends as readable text."""
    if not trends:
        return "No trend data available. Need at least 1 week of sessions."

    lines = [
        f"{'='*60}",
        "  FRICTION TREND REPORT",
        f"{'='*60}",
        "",
    ]

    for t in trends:
        direction = ""
        if len(trends) >= 2 and t == trends[-1]:
            prev = trends[-2]
            diff = t.high_friction_ratio - prev.high_friction_ratio
            if diff > 0.05:
                direction = " ↑ WORSENING"
            elif diff < -0.05:
                direction = " ↓ IMPROVING"
            else:
                direction = " → STABLE"

        lines.append(
            f"  {t.week_label}: "
            f"{t.total_sessions} sessions, "
            f"{t.total_minutes:.0f}min total, "
            f"friction: {t.high_friction_ratio:.0%}{direction}"
        )
        if t.top_friction_intents:
            lines.append(f"    Top friction: {', '.join(t.top_friction_intents)}")
        lines.append("")

    # Overall trajectory
    if len(trends) >= 2:
        first = trends[0].high_friction_ratio
        last = trends[-1].high_friction_ratio
        diff = last - first

        lines.append(f"  {'─'*50}")
        if diff > 0.1:
            lines.append(f"  ⚠ Friction is INCREASING ({first:.0%} → {last:.0%})")
            lines.append("  Your workflows are getting more chaotic over time.")
        elif diff < -0.1:
            lines.append(f"  ✓ Friction is DECREASING ({first:.0%} → {last:.0%})")
            lines.append("  Your workflow replacements are working.")
        else:
            lines.append(f"  Friction is STABLE ({first:.0%} → {last:.0%})")
        lines.append("")

    return "\n".join(lines)


def format_patterns_report(patterns: list[WorkflowPattern]) -> str:
    """Format detected patterns as readable text."""
    if not patterns:
        return "No recurring patterns detected. Need more data across multiple days."

    lines = [
        f"{'='*60}",
        "  RECURRING WORKFLOW PATTERNS",
        f"{'='*60}",
        "",
    ]

    for i, p in enumerate(patterns, 1):
        trend_marker = {
            "worsening": " ↑ WORSENING",
            "improving": " ↓ IMPROVING",
            "stable": "",
        }.get(p.trend, "")

        lines.extend([
            f"  {i}. {p.intent}",
            f"     Seen {p.occurrences} times | "
            f"Avg: {p.avg_duration_minutes:.0f}min | "
            f"Total: {p.total_time_invested_minutes:.0f}min",
            f"     Friction: {p.most_common_friction.value}{trend_marker} | "
            f"Avg switches: {p.avg_context_switches:.0f}",
            f"     Apps: {', '.join(p.apps_involved[:5])}",
            f"     First: {p.first_seen.strftime('%b %d')} | "
            f"Last: {p.last_seen.strftime('%b %d')}",
            "",
        ])

    # Summary
    total_time = sum(p.total_time_invested_minutes for p in patterns)
    high_friction_patterns = [
        p for p in patterns
        if p.most_common_friction in (FrictionLevel.HIGH, FrictionLevel.CRITICAL)
    ]

    lines.extend([
        f"  {'─'*50}",
        f"  Total patterns: {len(patterns)}",
        f"  Total time in patterns: {total_time:.0f} min ({total_time/60:.1f} hrs)",
        f"  High-friction patterns: {len(high_friction_patterns)}",
    ])

    if high_friction_patterns:
        lines.append(
            f"  → These {len(high_friction_patterns)} patterns are your replacement candidates."
        )
    lines.append("")

    return "\n".join(lines)
