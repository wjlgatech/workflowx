"""WorkflowX CLI — primary user interface.

Usage:
    workflowx status          # Show connection status
    workflowx capture         # Read events from Screenpipe and store
    workflowx analyze         # Cluster + infer intent from today's events
    workflowx validate        # Answer classification questions
    workflowx report          # Generate daily/weekly workflow report
    workflowx propose         # Generate replacement proposals for high-friction workflows
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


@click.group()
@click.version_option()
def cli() -> None:
    """WorkflowX: Observe workflows. Understand intent. Replace friction."""
    pass


# ── STATUS ────────────────────────────────────────────────────


@cli.command()
def status() -> None:
    """Show current WorkflowX status and connections."""
    from workflowx.capture.screenpipe import ScreenpipeAdapter
    from workflowx.config import load_config
    from workflowx.storage import LocalStore

    config = load_config()

    console.print("\n[bold]WorkflowX Status[/bold]\n")

    # Screenpipe
    sp = ScreenpipeAdapter(db_path=config.screenpipe_db_path)
    if sp.is_available():
        console.print(f"  Screenpipe:      [green]Connected[/green] ({sp.db_path})")
    else:
        console.print("  Screenpipe:      [red]Not found[/red]")

    # ActivityWatch
    try:
        from workflowx.capture.activitywatch import ActivityWatchAdapter
        aw = ActivityWatchAdapter(host=config.activitywatch_host)
        if aw.is_available():
            console.print(f"  ActivityWatch:   [green]Connected[/green] ({config.activitywatch_host})")
        else:
            console.print(f"  ActivityWatch:   [yellow]Not running[/yellow]")
    except Exception:
        console.print("  ActivityWatch:   [dim]Not installed[/dim]")

    # LLM
    console.print(f"  LLM Provider:    {config.llm_provider}")
    console.print(f"  LLM Model:       {config.llm_model}")

    has_key = bool(config.anthropic_api_key or config.openai_api_key)
    if has_key:
        console.print("  API Key:         [green]Configured[/green]")
    else:
        console.print("  API Key:         [yellow]Not set[/yellow] (set ANTHROPIC_API_KEY or OPENAI_API_KEY)")

    # Storage
    store = LocalStore(config.data_dir)
    today_sessions = store.load_sessions(date.today())
    pending_qs = store.load_pending_questions()
    console.print(f"  Data Dir:        {config.data_dir}")
    console.print(f"  Today's Sessions: {len(today_sessions)}")
    console.print(f"  Pending Questions: {len(pending_qs)}")

    console.print(f"  Version:         {_get_version()}")
    console.print()


# ── CAPTURE ───────────────────────────────────────────────────


@cli.command()
@click.option("--source", type=click.Choice(["screenpipe", "activitywatch", "all"]), default="all")
@click.option("--hours", default=24, help="Hours of history to read")
@click.option("--save/--no-save", default=True, help="Save events to local store")
def capture(source: str, hours: int, save: bool) -> None:
    """Read events from capture sources and store for analysis."""
    from workflowx.config import load_config
    from workflowx.inference.clusterer import cluster_into_sessions
    from workflowx.storage import LocalStore

    config = load_config()
    since = datetime.now() - timedelta(hours=hours)
    all_events = []

    # Screenpipe
    if source in ("screenpipe", "all"):
        from workflowx.capture.screenpipe import ScreenpipeAdapter
        sp = ScreenpipeAdapter(db_path=config.screenpipe_db_path)
        if sp.is_available():
            events = sp.read_events(since=since)
            all_events.extend(events)
            console.print(f"  Screenpipe: [green]{len(events)} events[/green]")
        else:
            console.print("  Screenpipe: [yellow]not available[/yellow]")

    # ActivityWatch
    if source in ("activitywatch", "all"):
        try:
            from workflowx.capture.activitywatch import ActivityWatchAdapter
            aw = ActivityWatchAdapter(host=config.activitywatch_host)
            if aw.is_available():
                events = aw.read_events(since=since)
                all_events.extend(events)
                console.print(f"  ActivityWatch: [green]{len(events)} events[/green]")
            else:
                console.print("  ActivityWatch: [yellow]not running[/yellow]")
        except ImportError:
            pass

    if not all_events:
        console.print("\n[red]No events captured.[/red] Is Screenpipe or ActivityWatch running?")
        return

    # Sort and deduplicate
    all_events.sort(key=lambda e: e.timestamp)
    console.print(f"\n[bold]Total: {len(all_events)} events[/bold] from last {hours} hours")

    # Cluster into sessions
    sessions = cluster_into_sessions(
        all_events,
        gap_minutes=config.session_gap_minutes,
        min_events=config.min_session_events,
    )
    console.print(f"Clustered into [bold]{len(sessions)} sessions[/bold]")

    # Save
    if save:
        store = LocalStore(config.data_dir)
        path = store.save_sessions(sessions)
        console.print(f"Saved to {path}")

    # Show sample
    _show_sessions_table(sessions[:8])
    if len(sessions) > 8:
        console.print(f"  ... and {len(sessions) - 8} more sessions")


# ── ANALYZE ───────────────────────────────────────────────────


@cli.command()
@click.option("--hours", default=24, help="Hours of history to analyze")
def analyze(hours: int) -> None:
    """Run LLM intent inference on today's sessions."""
    from workflowx.config import load_config
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)
    sessions = store.load_sessions(date.today())

    if not sessions:
        console.print("[yellow]No sessions found for today. Run 'workflowx capture' first.[/yellow]")
        return

    # Filter to un-analyzed sessions
    to_analyze = [s for s in sessions if not s.inferred_intent or s.inferred_intent == "inference_failed"]

    if not to_analyze:
        console.print(f"All {len(sessions)} sessions already analyzed.")
        _show_sessions_table(sessions)
        return

    console.print(f"Analyzing {len(to_analyze)} sessions with {config.llm_provider}/{config.llm_model}...")

    try:
        client = config.get_llm_client()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        return

    from workflowx.inference.intent import infer_intent

    questions = []

    async def _run_inference():
        for i, session in enumerate(to_analyze, 1):
            console.print(f"  [{i}/{len(to_analyze)}] Analyzing {session.start_time.strftime('%H:%M')}-{session.end_time.strftime('%H:%M')}...")
            updated, question = await infer_intent(session, client, model=config.llm_model)
            if question:
                questions.append(question)
            # Update in full list
            for j, s in enumerate(sessions):
                if s.id == updated.id:
                    sessions[j] = updated

    asyncio.run(_run_inference())

    # Save updated sessions
    store.save_sessions(sessions)
    if questions:
        store.save_questions(questions)
        console.print(f"\n[yellow]{len(questions)} questions need your input.[/yellow] Run 'workflowx validate'")

    console.print(f"\n[green]Analysis complete.[/green]")
    _show_sessions_table(sessions)


# ── VALIDATE ──────────────────────────────────────────────────


@cli.command()
def validate() -> None:
    """Answer classification questions to improve workflow understanding."""
    from workflowx.config import load_config
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)
    questions = store.load_pending_questions()

    if not questions:
        console.print("[green]No pending questions. All sessions validated.[/green]")
        return

    console.print(f"\n[bold]{len(questions)} questions need your input:[/bold]\n")

    for q in questions:
        console.print(Panel(
            f"[bold]{q.question}[/bold]\n\n"
            f"Context: {q.context}\n\n"
            + "\n".join(f"  [{i+1}] {opt}" for i, opt in enumerate(q.options))
            + "\n  [0] Something else",
            title=f"Session {q.session_id[:8]}",
        ))

        choice = click.prompt("Your answer", type=int, default=1)
        if choice == 0:
            answer = click.prompt("What were you doing?")
        elif 1 <= choice <= len(q.options):
            answer = q.options[choice - 1]
        else:
            answer = q.options[0]

        store.answer_question(q.session_id, answer)
        console.print(f"  [green]Recorded: {answer}[/green]\n")

    # Update sessions with validated labels
    sessions = store.load_sessions(date.today())
    for session in sessions:
        for q in questions:
            if q.session_id == session.id and q.answered:
                session.user_validated = True
                session.user_label = q.answer
    store.save_sessions(sessions)

    console.print(f"[green]All {len(questions)} questions answered.[/green]")


# ── REPORT ────────────────────────────────────────────────────


@cli.command()
@click.option("--period", type=click.Choice(["daily", "weekly"]), default="daily")
def report(period: str) -> None:
    """Generate a workflow report."""
    from workflowx.config import load_config
    from workflowx.inference.reporter import (
        format_weekly_summary,
        generate_daily_report,
        generate_weekly_report,
    )
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)

    if period == "daily":
        sessions = store.load_sessions(date.today())
        if not sessions:
            console.print("[yellow]No sessions today. Run 'workflowx capture' first.[/yellow]")
            return
        text = generate_daily_report(sessions, hourly_rate_usd=config.hourly_rate_usd)
        console.print(text)

    elif period == "weekly":
        # Load last 7 days
        today = date.today()
        all_sessions = []
        for i in range(7):
            d = today - timedelta(days=i)
            all_sessions.extend(store.load_sessions(d))

        if not all_sessions:
            console.print("[yellow]No sessions in the last 7 days.[/yellow]")
            return

        weekly = generate_weekly_report(all_sessions, hourly_rate_usd=config.hourly_rate_usd)
        store.save_report(weekly)
        text = format_weekly_summary(weekly, hourly_rate=config.hourly_rate_usd)
        console.print(text)


# ── PROPOSE ───────────────────────────────────────────────────


@cli.command()
@click.option("--top", default=3, help="Number of top friction workflows to propose replacements for")
def propose(top: int) -> None:
    """Generate replacement proposals for high-friction workflows."""
    from workflowx.config import load_config
    from workflowx.inference.intent import diagnose_workflow
    from workflowx.replacement.engine import propose_replacement
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)
    sessions = store.load_sessions(date.today())

    if not sessions:
        console.print("[yellow]No sessions. Run 'workflowx capture' + 'workflowx analyze' first.[/yellow]")
        return

    # Find highest-friction sessions
    analyzed = [s for s in sessions if s.inferred_intent]
    if not analyzed:
        console.print("[yellow]Sessions not yet analyzed. Run 'workflowx analyze' first.[/yellow]")
        return

    diagnoses = [diagnose_workflow(s, config.hourly_rate_usd) for s in analyzed]
    ranked = sorted(
        zip(diagnoses, analyzed),
        key=lambda pair: pair[0].automation_potential * pair[0].total_time_minutes,
        reverse=True,
    )[:top]

    if not ranked:
        console.print("[green]No high-friction workflows found. Nice.[/green]")
        return

    console.print(f"\n[bold]Generating {len(ranked)} replacement proposals...[/bold]\n")

    try:
        client = config.get_llm_client()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        return

    async def _run_proposals():
        for i, (diag, session) in enumerate(ranked, 1):
            console.print(f"  [{i}/{len(ranked)}] {diag.intent}...")
            proposal = await propose_replacement(diag, session, client, config.llm_model)

            console.print(Panel(
                f"[bold]Original:[/bold] {proposal.original_workflow}\n\n"
                f"[bold green]Proposed:[/bold green] {proposal.proposed_workflow}\n\n"
                f"[bold]Mechanism:[/bold] {proposal.mechanism}\n\n"
                f"Time: {diag.total_time_minutes:.0f}min → {proposal.estimated_time_after_minutes:.0f}min "
                f"([green]save {proposal.estimated_savings_minutes_per_week:.0f}min/week[/green])\n"
                f"Confidence: {proposal.confidence:.0%}\n"
                + (f"New tools needed: {', '.join(proposal.requires_new_tools)}\n" if proposal.requires_new_tools else "")
                + (f"\n[dim]Agenticom YAML generated ({len(proposal.agenticom_workflow_yaml)} chars)[/dim]" if proposal.agenticom_workflow_yaml else ""),
                title=f"Replacement #{i}",
                border_style="green",
            ))

    asyncio.run(_run_proposals())


# ── HELPERS ───────────────────────────────────────────────────


def _show_sessions_table(sessions: list) -> None:
    """Display sessions as a Rich table."""
    if not sessions:
        return

    table = Table(title="Workflow Sessions")
    table.add_column("Time", style="cyan")
    table.add_column("Duration", style="white")
    table.add_column("Apps", style="green", max_width=25)
    table.add_column("Switches", style="yellow", justify="right")
    table.add_column("Friction", style="red")
    table.add_column("Intent", style="white", max_width=30)

    friction_colors = {
        "low": "green",
        "medium": "yellow",
        "high": "red",
        "critical": "bold red",
    }

    for s in sessions:
        color = friction_colors.get(s.friction_level.value, "white")
        intent = s.inferred_intent[:30] if s.inferred_intent else "[dim]--[/dim]"

        table.add_row(
            f"{s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}",
            f"{s.total_duration_minutes:.0f} min",
            ", ".join(s.apps_used[:3]),
            str(s.context_switches),
            f"[{color}]{s.friction_level.value}[/{color}]",
            intent,
        )

    console.print(table)


def _get_version() -> str:
    try:
        from workflowx import __version__
        return __version__
    except ImportError:
        return "unknown"


if __name__ == "__main__":
    cli()
