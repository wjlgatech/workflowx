"""WorkflowX CLI — primary user interface.

Usage:
    workflowx status          # Show connection status
    workflowx capture         # Read events from Screenpipe and store
    workflowx analyze         # Cluster + infer intent from today's events
    workflowx validate        # Answer classification questions
    workflowx report          # Generate daily/weekly workflow report
    workflowx propose         # Generate replacement proposals for high-friction workflows
    workflowx patterns        # Detect recurring workflow patterns (Phase 2)
    workflowx trends          # Show weekly friction trends (Phase 2)
    workflowx export          # Export data to JSON/CSV (Phase 2)
    workflowx mcp             # Start MCP server (Phase 2)
    workflowx adopt           # Mark a proposal as adopted (Phase 3)
    workflowx measure         # Measure actual ROI of adopted replacements (Phase 3)
    workflowx dashboard       # Generate static HTML ROI dashboard (Phase 3)
    workflowx serve           # Live dashboard server with Update button (Phase 3)
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path

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
    patterns = store.load_patterns()
    outcomes = store.load_outcomes()
    console.print(f"  Data Dir:        {config.data_dir}")
    console.print(f"  Today's Sessions: {len(today_sessions)}")
    console.print(f"  Pending Questions: {len(pending_qs)}")
    console.print(f"  Patterns Tracked: {len(patterns)}")
    console.print(f"  Outcomes Tracked: {len(outcomes)}")

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

    # Sort by timestamp
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


# ── PATTERNS (Phase 2) ───────────────────────────────────────


@cli.command()
@click.option("--days", default=30, help="Number of days to scan for patterns")
@click.option("--min-occurrences", default=2, help="Minimum times a pattern must appear")
def patterns(days: int, min_occurrences: int) -> None:
    """Detect recurring workflow patterns across multiple days."""
    from workflowx.config import load_config
    from workflowx.inference.patterns import detect_patterns, format_patterns_report
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)

    # Load sessions across the date range
    today = date.today()
    all_sessions = []
    for i in range(days):
        d = today - timedelta(days=i)
        all_sessions.extend(store.load_sessions(d))

    if not all_sessions:
        console.print(f"[yellow]No sessions in the last {days} days.[/yellow]")
        return

    console.print(f"Scanning {len(all_sessions)} sessions across {days} days...\n")

    found = detect_patterns(all_sessions, min_occurrences=min_occurrences)
    store.save_patterns(found)

    text = format_patterns_report(found)
    console.print(text)


# ── TRENDS (Phase 2) ─────────────────────────────────────────


@cli.command()
@click.option("--weeks", default=4, help="Number of weeks to show")
def trends(weeks: int) -> None:
    """Show weekly friction trends."""
    from workflowx.config import load_config
    from workflowx.inference.patterns import compute_friction_trends, format_trends_report
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)

    # Load enough sessions
    today = date.today()
    all_sessions = []
    for i in range(weeks * 7 + 7):  # Extra week for padding
        d = today - timedelta(days=i)
        all_sessions.extend(store.load_sessions(d))

    if not all_sessions:
        console.print("[yellow]No sessions found. Run 'workflowx capture' first.[/yellow]")
        return

    computed = compute_friction_trends(all_sessions, num_weeks=weeks)
    text = format_trends_report(computed)
    console.print(text)


# ── EXPORT (Phase 2) ─────────────────────────────────────────


@cli.command(name="export")
@click.option("--format", "fmt", type=click.Choice(["json", "csv"]), default="json")
@click.option("--data", type=click.Choice(["sessions", "patterns", "trends"]), default="sessions")
@click.option("--days", default=7, help="Number of days of sessions to export")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
def export_cmd(fmt: str, data: str, days: int, output: str | None) -> None:
    """Export workflow data to JSON or CSV."""
    from workflowx.config import load_config
    from workflowx.export import (
        export_to_file,
        patterns_to_csv,
        patterns_to_json,
        sessions_to_csv,
        sessions_to_json,
        trends_to_csv,
        trends_to_json,
    )
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)

    if data == "sessions":
        today = date.today()
        all_sessions = []
        for i in range(days):
            d = today - timedelta(days=i)
            all_sessions.extend(store.load_sessions(d))

        if not all_sessions:
            console.print("[yellow]No sessions to export.[/yellow]")
            return

        content = sessions_to_json(all_sessions) if fmt == "json" else sessions_to_csv(all_sessions)
        default_name = f"workflowx-sessions-{days}d.{fmt}"

    elif data == "patterns":
        found = store.load_patterns()
        if not found:
            console.print("[yellow]No patterns found. Run 'workflowx patterns' first.[/yellow]")
            return
        content = patterns_to_json(found) if fmt == "json" else patterns_to_csv(found)
        default_name = f"workflowx-patterns.{fmt}"

    elif data == "trends":
        from workflowx.inference.patterns import compute_friction_trends
        today = date.today()
        all_sessions = []
        for i in range(35):
            d = today - timedelta(days=i)
            all_sessions.extend(store.load_sessions(d))
        computed = compute_friction_trends(all_sessions)
        if not computed:
            console.print("[yellow]No trends to export.[/yellow]")
            return
        content = trends_to_json(computed) if fmt == "json" else trends_to_csv(computed)
        default_name = f"workflowx-trends.{fmt}"
    else:
        console.print("[red]Unknown data type.[/red]")
        return

    out_path = Path(output) if output else Path(default_name)
    export_to_file(content, out_path)
    console.print(f"[green]Exported to {out_path}[/green] ({len(content)} bytes)")


# ── MCP (Phase 2) ────────────────────────────────────────────


@cli.command()
@click.option("--http", "use_http", is_flag=True, help="Use HTTP transport instead of stdio")
@click.option("--port", default=8765, help="HTTP port (only with --http)")
def mcp(use_http: bool, port: int) -> None:
    """Start MCP server for Claude/Cursor integration."""
    from workflowx.mcp_server import run_mcp_http, run_mcp_stdio

    if use_http:
        console.print(f"Starting MCP server on http://localhost:{port}")
        console.print("Add to Claude Code: workflowx mcp --http --port {port}")
        run_mcp_http(port=port)
    else:
        # Stdio mode — no console output (it would break the protocol)
        run_mcp_stdio()


# ── ADOPT (Phase 3) ──────────────────────────────────────────


@cli.command()
@click.argument("intent")
@click.option("--before-minutes", type=float, required=True, help="Minutes/week before replacement")
def adopt(intent: str, before_minutes: float) -> None:
    """Mark a workflow replacement as adopted and start tracking ROI.

    INTENT is the workflow intent string (e.g., "competitive research").
    """
    from workflowx.measurement import create_outcome
    from workflowx.models import ReplacementProposal
    from workflowx.config import load_config
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)

    # Create a lightweight proposal reference
    proposal = ReplacementProposal(
        diagnosis_id=f"adopted_{intent.lower().replace(' ', '_')[:30]}",
        original_workflow=intent,
        proposed_workflow="(user-adopted replacement)",
        mechanism="User confirmed adoption",
    )

    outcome = create_outcome(proposal, before_minutes_per_week=before_minutes)
    store.save_outcome(outcome)

    console.print(f"\n[green]Tracking started![/green]")
    console.print(f"  Intent: {intent}")
    console.print(f"  Baseline: {before_minutes:.0f} min/week")
    console.print(f"  Status: measuring")
    console.print(f"\nRun 'workflowx measure' after a week to see actual savings.\n")


# ── MEASURE (Phase 3) ────────────────────────────────────────


@cli.command()
@click.option("--days", default=7, help="Days of recent data to measure against")
def measure(days: int) -> None:
    """Measure actual ROI of adopted replacements."""
    from workflowx.config import load_config
    from workflowx.measurement import format_roi_report, measure_outcome
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)
    outcomes = store.load_outcomes()

    if not outcomes:
        console.print("[yellow]No outcomes tracked. Run 'workflowx adopt' first.[/yellow]")
        return

    # Load recent sessions
    today = date.today()
    recent_sessions = []
    for i in range(days):
        d = today - timedelta(days=i)
        recent_sessions.extend(store.load_sessions(d))

    console.print(f"Measuring {len(outcomes)} outcomes against {len(recent_sessions)} recent sessions...\n")

    active = [o for o in outcomes if o.status in ("measuring", "adopted")]
    for outcome in active:
        outcome = measure_outcome(outcome, recent_sessions, lookback_days=days)
        store.save_outcome(outcome)

    # Reload and display
    outcomes = store.load_outcomes()
    text = format_roi_report(outcomes, hourly_rate=config.hourly_rate_usd)
    console.print(text)


# ── DASHBOARD (Phase 3) ──────────────────────────────────────


@cli.command()
@click.option("--output", "-o", type=click.Path(), default="workflowx-dashboard.html")
def dashboard(output: str) -> None:
    """Generate an HTML ROI dashboard."""
    from workflowx.config import load_config
    from workflowx.dashboard import generate_dashboard_html
    from workflowx.inference.patterns import compute_friction_trends, detect_patterns
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)

    # Load data
    today = date.today()
    all_sessions = []
    for i in range(30):
        d = today - timedelta(days=i)
        all_sessions.extend(store.load_sessions(d))

    if not all_sessions:
        console.print("[yellow]No sessions found. Run 'workflowx capture' first.[/yellow]")
        return

    found_patterns = detect_patterns(all_sessions)
    computed_trends = compute_friction_trends(all_sessions)
    outcomes = store.load_outcomes()

    html = generate_dashboard_html(
        trends=computed_trends,
        patterns=found_patterns,
        outcomes=outcomes,
        hourly_rate=config.hourly_rate_usd,
    )

    out_path = Path(output)
    out_path.write_text(html)
    console.print(f"[green]Dashboard generated: {out_path}[/green]")
    console.print(f"Open in your browser to see the ROI dashboard.")


# ── SERVE (Phase 3) ──────────────────────────────────────────


@cli.command()
@click.option("--port", default=7788, help="Port to serve on (default: 7788)")
@click.option("--file", "-f", "file_path", default=None, type=click.Path(exists=True),
              help="Serve a specific HTML file instead of the live WorkflowX dashboard")
@click.option("--watch", "-w", is_flag=True, default=False,
              help="Auto-reload browser when data or file changes (requires watchdog)")
def serve(port: int, file_path: str | None, watch: bool) -> None:
    """Start a live server at http://localhost:PORT.

    Default mode: serves the WorkflowX live dashboard. Fetches fresh data
    on the Update button click. With --watch, auto-refreshes whenever the
    daemon writes new session or pattern data — no button click needed.

    File mode (--file): serves any HTML file with hot-reload. Use this
    while iterating on a dashboard HTML in your editor — the browser
    updates on every save without switching windows to refresh manually.

        workflowx serve --file workflowx-demo-dashboard.html --watch

    Press Ctrl+C to stop.
    """
    from pathlib import Path

    from workflowx.config import load_config
    from workflowx.server import run_file_server, run_server
    from workflowx.storage import LocalStore

    url = f"http://localhost:{port}"
    console.print(f"\n[bold]WorkflowX Server[/bold]")
    console.print(f"  URL:   [link={url}]{url}[/link]")

    if file_path:
        p = Path(file_path)
        console.print(f"  File:  {p.resolve()}")
        console.print(f"  Watch: {'[green]on[/green] (auto-reload on save)' if watch else 'off'}")
    else:
        config = load_config()
        console.print(f"  Data:  {config.data_dir}")
        console.print(f"  Watch: {'[green]on[/green] (auto-refresh on new data)' if watch else 'off (Update button)'}")

    console.print(f"  Press [bold]Ctrl+C[/bold] to stop\n")

    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass

    try:
        if file_path:
            run_file_server(Path(file_path), port=port, watch=watch)
        else:
            config = load_config()
            store = LocalStore(config.data_dir)
            run_server(config, store, port=port, watch=watch)
    except KeyboardInterrupt:
        console.print("\n[dim]Server stopped.[/dim]")
    except OSError as e:
        if "Address already in use" in str(e):
            console.print(
                f"[red]Port {port} is already in use.[/red] "
                f"Try: workflowx serve --port {port + 1}"
            )
        else:
            raise


# ── SCAFFOLD ──────────────────────────────────────────────────


@cli.command()
@click.option(
    "--output", "-o",
    type=click.Path(),
    default="workflowx-dashboard.html",
    help="Output file path (default: workflowx-dashboard.html)",
)
def scaffold(output: str) -> None:
    """Generate a clean, data-wired, editable HTML dashboard.

    Unlike 'workflowx dashboard' (read-only static snapshot), the scaffold
    is designed to be edited — by you or Claude — without rebuilding the
    whole file from scratch. All WorkflowX data is embedded as a plain JS
    object (WX_DATA) that Claude can read and reference by name.

    Typical workflow:

    \b
        workflowx scaffold --output my-dashboard.html
        workflowx serve --file my-dashboard.html --watch
        # Ask Claude to edit my-dashboard.html
        # Browser auto-reloads on every save — no manual refresh

    Regenerate data at any time (keeps your HTML edits):

    \b
        workflowx scaffold --output my-dashboard.html
    """
    from workflowx.config import load_config
    from workflowx.scaffold import generate_scaffold_html
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)

    from pathlib import Path

    out = Path(output)
    html = generate_scaffold_html(config, store, hourly_rate=config.hourly_rate_usd)
    out.write_text(html)

    console.print(f"\n[bold]Scaffold generated:[/bold] {out.resolve()}")
    console.print(f"  Sessions embedded: [green]✓[/green]  Patterns: [green]✓[/green]  Trends: [green]✓[/green]")
    console.print(f"\nNext steps:")
    console.print(f"  [dim]workflowx serve --file {output} --watch[/dim]  ← live-reload preview")
    console.print(f"  [dim]# Ask Claude to edit {output} — browser updates on every save[/dim]\n")


# ── DEMO ──────────────────────────────────────────────────────


@cli.command()
@click.option("--days", default=14, help="Number of synthetic days to generate")
@click.option("--output", "-o", type=click.Path(), default="workflowx-demo-dashboard.html")
@click.option("--seed", default=42, help="Random seed for reproducibility")
def demo(days: int, output: str, seed: int) -> None:
    """Run full pipeline on synthetic data — proof of life in 10 seconds.

    Generates realistic workflow data for a knowledge worker, runs the full
    WorkflowX pipeline (capture → cluster → infer → detect patterns →
    compute trends → diagnose → propose → measure ROI), and opens an
    HTML dashboard showing everything.

    No Screenpipe needed. No API key needed. Pure local demo.
    """
    from workflowx.demo import run_demo_pipeline
    from workflowx.inference.patterns import format_patterns_report, format_trends_report
    from workflowx.measurement import format_roi_report

    console.print("\n[bold]WorkflowX Demo — Full Pipeline[/bold]\n")
    console.print("Generating synthetic data for a knowledge worker's 2-week history...\n")

    result = run_demo_pipeline(
        output_dir=Path(output).parent,
        num_days=days,
        seed=seed,
    )
    # Rename dashboard to user's output path
    generated = Path(result["dashboard_path"])
    out_path = Path(output)
    if generated != out_path:
        out_path.write_text(generated.read_text())

    # Show summary
    console.print(f"  Sessions generated:     [bold]{result['sessions']}[/bold]")
    console.print(f"  Patterns detected:      [bold]{result['patterns']}[/bold]")
    console.print(f"  Weeks of trends:        [bold]{result['trends']}[/bold]")
    console.print(f"  Replacement proposals:  [bold]{result['proposals']}[/bold]")
    console.print(f"  Outcomes tracked:       [bold]{result['outcomes']}[/bold]")
    console.print(f"  Friction trajectory:    [bold]{result['friction_trajectory']}[/bold]")
    console.print()

    # Top patterns
    if result["top_patterns"]:
        console.print("[bold]Top Recurring Patterns:[/bold]")
        for p in result["top_patterns"]:
            console.print(
                f"  • {p['intent']} — {p['occurrences']}x, "
                f"{p['total_min']:.0f} min invested"
            )
        console.print()

    # ROI
    roi = result["roi"]
    weekly_savings_hrs = roi["total_weekly_savings_hours"]
    weekly_usd = weekly_savings_hrs * 75.0
    console.print(f"[bold green]Potential Weekly Savings: {roi['total_weekly_savings_minutes']:.0f} min ({weekly_savings_hrs:.1f} hrs) = ${weekly_usd:.0f}/week[/bold green]")
    console.print(f"  Adopted: {roi['adopted']} | Rejected: {roi['rejected']} | Measuring: {roi['measuring']}")
    console.print()

    console.print(f"[bold]Dashboard: [link=file://{out_path.absolute()}]{out_path}[/link][/bold]")
    console.print(f"Open in your browser to explore the full ROI dashboard.\n")


# ── DAEMON ────────────────────────────────────────────────────


@cli.group()
def daemon() -> None:
    """Manage the WorkflowX background daemon.

    The daemon runs the full pipeline automatically:\n
      health:  every 5 min        — Screenpipe liveness\n
      capture: 12:55 + 17:55 WD  — Roll up last 4h of events\n
      analyze: 13:00 + 18:00 WD  — LLM inference; notifies on HIGH/CRITICAL\n
      measure: 07:00 daily        — Adaptive ROI measurement\n
      brief:   08:30 WD           — Morning summary notification
    """
    pass


@daemon.command("start")
def daemon_start() -> None:
    """Install launchd agent and start the daemon (auto-restarts on login)."""
    import subprocess
    import sys

    from workflowx.config import load_config
    from workflowx.daemon import PLIST_PATH, install_launchd_plist, is_daemon_running

    if sys.platform != "darwin":
        console.print("[red]The daemon uses launchd — macOS only.[/red]")
        console.print("On Linux/Windows: run 'workflowx daemon run' directly in a terminal.")
        return

    config = load_config()
    pid_path = Path(config.data_dir) / "daemon.pid"

    if is_daemon_running(pid_path):
        console.print("[yellow]Daemon is already running.[/yellow] Use 'workflowx daemon status'.")
        return

    log_path = Path(config.data_dir) / "daemon.log"
    plist_path = install_launchd_plist(log_path)
    console.print(f"  Plist:  {plist_path}")
    console.print(f"  Log:    {log_path}")

    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        console.print("\n[green]Daemon started.[/green]")
        console.print("  Runs at login, restarts automatically if it crashes.")
        console.print("  Stop: workflowx daemon stop")
    else:
        console.print(f"[red]launchctl load failed:[/red] {result.stderr.strip() or result.stdout.strip()}")
        console.print("You can still run the daemon manually: workflowx daemon run")


@daemon.command("stop")
def daemon_stop() -> None:
    """Stop the daemon and remove the launchd agent."""
    import subprocess
    import sys

    from workflowx.daemon import PLIST_PATH, uninstall_launchd_plist

    if sys.platform != "darwin":
        console.print("[yellow]No launchd agent on this platform.[/yellow]")
        console.print("Kill the 'workflowx daemon run' process manually.")
        return

    result = subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        capture_output=True, text=True,
    )
    removed = uninstall_launchd_plist()

    if result.returncode == 0 or removed:
        console.print("[green]Daemon stopped and plist removed.[/green]")
    else:
        msg = result.stderr.strip() or result.stdout.strip()
        console.print(f"[yellow]Daemon was not running (or launchctl failed).[/yellow]")
        if msg:
            console.print(f"  {msg}")


@daemon.command("status")
def daemon_status() -> None:
    """Show daemon status, last run times, and upcoming schedule."""
    from workflowx.config import load_config
    from workflowx.daemon import (
        ANALYZE_TIMES,
        BRIEF_TIMES,
        CAPTURE_TIMES,
        MEASURE_TIMES,
        PLIST_PATH,
        is_daemon_running,
        next_fire_time,
        read_state,
    )

    config = load_config()
    pid_path   = Path(config.data_dir) / "daemon.pid"
    state_path = Path(config.data_dir) / "daemon_state.json"

    running = is_daemon_running(pid_path)
    status_str = "[green]Running[/green]" if running else "[red]Stopped[/red]"
    plist_str  = "installed" if PLIST_PATH.exists() else "[dim]not installed[/dim]"

    console.print(f"\n[bold]WorkflowX Daemon[/bold]")
    console.print(f"  Status:  {status_str}")
    console.print(f"  Plist:   {plist_str}")
    console.print(f"  Log:     {config.data_dir}/daemon.log")

    state = read_state(state_path)
    if state.jobs:
        table = Table(title="Job History", show_header=True)
        table.add_column("Job",      style="cyan")
        table.add_column("Last Run", style="white")
        table.add_column("Status",   style="white")
        table.add_column("Next Run", style="white")

        status_colors = {"ok": "green", "error": "red", "skipped": "yellow", "pending": "dim"}

        for name, job in sorted(state.jobs.items()):
            last  = job.last_run.strftime("%a %H:%M") if job.last_run else "—"
            nxt   = job.next_run.strftime("%a %H:%M") if job.next_run else "—"
            color = status_colors.get(job.last_status, "white")
            err   = f" ({job.error_message[:40]})" if job.error_message else ""
            table.add_row(
                name,
                last,
                f"[{color}]{job.last_status}{err}[/{color}]",
                nxt,
            )
        console.print()
        console.print(table)

    # Show upcoming schedule from now
    now = datetime.now()
    console.print(f"\n[bold]Upcoming Runs[/bold]  (as of {now.strftime('%H:%M')})")
    upcoming = [
        ("capture", next_fire_time(CAPTURE_TIMES, weekdays_only=False, now=now)),
        ("analyze", next_fire_time(ANALYZE_TIMES, weekdays_only=False, now=now)),
        ("measure", next_fire_time(MEASURE_TIMES, weekdays_only=False, now=now)),
        ("brief",   next_fire_time(BRIEF_TIMES,   weekdays_only=True,  now=now)),
    ]
    for name, dt in sorted(upcoming, key=lambda x: x[1]):
        delta = dt - now
        h     = int(delta.total_seconds() // 3600)
        m     = int((delta.total_seconds() % 3600) // 60)
        console.print(f"  {name:10s}  {dt.strftime('%a %H:%M')}  (in {h}h {m:02d}m)")

    if state.screenpipe_last_checked:
        health_str = "[green]healthy[/green]" if state.screenpipe_healthy else "[red]unhealthy[/red]"
        checked    = state.screenpipe_last_checked.strftime("%H:%M")
        console.print(f"\n  Screenpipe: {health_str}  (last checked {checked})")

    console.print()


@daemon.command("run")
def daemon_run() -> None:
    """Run the daemon event loop directly (used by launchd — not for manual use).

    For manual use, prefer 'workflowx daemon start' which installs the
    launchd agent so the daemon survives reboots and restarts automatically.
    """
    from workflowx.config import load_config
    from workflowx.daemon import run_daemon
    from workflowx.storage import LocalStore

    config     = load_config()
    store      = LocalStore(config.data_dir)
    data_dir   = Path(config.data_dir)
    state_path = data_dir / "daemon_state.json"
    pid_path   = data_dir / "daemon.pid"

    try:
        run_daemon(config, store, state_path, pid_path)
    except KeyboardInterrupt:
        console.print("\n[dim]Daemon stopped.[/dim]")


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
