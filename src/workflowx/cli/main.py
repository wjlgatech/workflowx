"""WorkflowX CLI — primary user interface.

Usage:
    workflowx capture        # Start reading events from Screenpipe
    workflowx analyze        # Cluster + infer intent from today's events
    workflowx report         # Generate weekly workflow report
    workflowx validate       # Answer classification questions
    workflowx status         # Show current tracking status
"""

from __future__ import annotations

from datetime import datetime, timedelta

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
@click.version_option()
def cli() -> None:
    """WorkflowX: Observe workflows. Understand intent. Replace friction."""
    pass


@cli.command()
@click.option("--db", default=None, help="Path to Screenpipe SQLite database")
@click.option("--hours", default=24, help="Hours of history to read")
def capture(db: str | None, hours: int) -> None:
    """Read events from Screenpipe and store for analysis."""
    from workflowx.capture.screenpipe import ScreenpipeAdapter

    adapter = ScreenpipeAdapter(db_path=db)

    if not adapter.is_available():
        console.print(
            "[red]Screenpipe database not found.[/red]\n"
            "Install Screenpipe: https://github.com/mediar-ai/screenpipe\n"
            "Or specify path: workflowx capture --db /path/to/db.sqlite"
        )
        return

    since = datetime.now() - timedelta(hours=hours)
    events = adapter.read_events(since=since)

    console.print(f"[green]Read {len(events)} events[/green] from last {hours} hours")

    if events:
        table = Table(title="Recent Events (sample)")
        table.add_column("Time", style="cyan")
        table.add_column("App", style="green")
        table.add_column("Window", style="white", max_width=40)

        for e in events[:10]:
            table.add_row(
                e.timestamp.strftime("%H:%M:%S"),
                e.app_name,
                e.window_title[:40],
            )

        console.print(table)
        if len(events) > 10:
            console.print(f"  ... and {len(events) - 10} more events")


@cli.command()
@click.option("--hours", default=24, help="Hours of history to analyze")
@click.option("--gap", default=5.0, help="Gap (minutes) between sessions")
def analyze(hours: int, gap: float) -> None:
    """Cluster events into workflow sessions and show friction analysis."""
    from workflowx.capture.screenpipe import ScreenpipeAdapter
    from workflowx.inference.clusterer import cluster_into_sessions

    adapter = ScreenpipeAdapter()
    if not adapter.is_available():
        console.print("[red]Screenpipe not available. Run 'workflowx capture' first.[/red]")
        return

    since = datetime.now() - timedelta(hours=hours)
    events = adapter.read_events(since=since)
    sessions = cluster_into_sessions(events, gap_minutes=gap)

    console.print(f"\n[bold]Found {len(sessions)} workflow sessions[/bold]\n")

    table = Table(title="Workflow Sessions")
    table.add_column("Time", style="cyan")
    table.add_column("Duration", style="white")
    table.add_column("Apps", style="green", max_width=30)
    table.add_column("Switches", style="yellow", justify="right")
    table.add_column("Friction", style="red")

    for s in sessions:
        friction_colors = {
            "low": "green",
            "medium": "yellow",
            "high": "red",
            "critical": "bold red",
        }
        color = friction_colors.get(s.friction_level.value, "white")

        table.add_row(
            f"{s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}",
            f"{s.total_duration_minutes:.0f} min",
            ", ".join(s.apps_used[:3]),
            str(s.context_switches),
            f"[{color}]{s.friction_level.value}[/{color}]",
        )

    console.print(table)

    # Summary stats
    total_min = sum(s.total_duration_minutes for s in sessions)
    high_friction = [s for s in sessions if s.friction_level.value in ("high", "critical")]
    console.print(f"\nTotal tracked: [bold]{total_min:.0f} min[/bold]")
    console.print(
        f"High-friction sessions: [bold red]{len(high_friction)}[/bold red] "
        f"({sum(s.total_duration_minutes for s in high_friction):.0f} min)"
    )


@cli.command()
def status() -> None:
    """Show current WorkflowX status."""
    from workflowx.capture.screenpipe import ScreenpipeAdapter

    adapter = ScreenpipeAdapter()

    console.print("\n[bold]WorkflowX Status[/bold]\n")

    if adapter.is_available():
        console.print(f"  Screenpipe: [green]Connected[/green] ({adapter.db_path})")
    else:
        console.print("  Screenpipe: [red]Not found[/red]")

    console.print(f"  Version: {_get_version()}")
    console.print()


def _get_version() -> str:
    try:
        from workflowx import __version__
        return __version__
    except ImportError:
        return "unknown"


if __name__ == "__main__":
    cli()
