"""CLI entry-point for monitor-agent-ai."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .agent import MonitorAgent
from .analyzer import AppAnalyzer

console = Console()

VALID_STACKS = ("prometheus", "datadog", "cloudwatch")


@click.group()
def cli() -> None:
    """monitor-agent-ai — AI-powered monitoring setup."""


@cli.command()
@click.option(
    "--src",
    default=".",
    show_default=True,
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Path to the application source directory to analyse.",
)
@click.option(
    "--output",
    default="monitoring",
    show_default=True,
    help="Output directory for generated monitoring artefacts.",
)
@click.option(
    "--stack",
    default="prometheus",
    show_default=True,
    type=click.Choice(VALID_STACKS, case_sensitive=False),
    help="Target monitoring stack.",
)
@click.option(
    "--api-key",
    envvar="ANTHROPIC_API_KEY",
    default=None,
    help="Anthropic API key (falls back to ANTHROPIC_API_KEY env var).",
)
@click.option(
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress per-step progress output.",
)
def generate(
    src: str,
    output: str,
    stack: str,
    api_key: str | None,
    quiet: bool,
) -> None:
    """
    Analyse an application and generate monitoring artefacts.

    For each detected concern the agent writes:

    \b
      - Prometheus alert rules YAML
      - Grafana dashboard JSON
      - Markdown runbook

    Examples:

    \b
      monitor-agent generate --src ./my-app --output ./monitoring
      monitor-agent generate --src . --stack datadog
    """
    src_path = Path(src).resolve()
    out_path = Path(output).resolve()

    # --- Static pre-analysis -------------------------------------------
    console.rule("[bold cyan]Monitor Agent[/bold cyan]")
    console.print(f"Source  : [green]{src_path}[/green]")
    console.print(f"Output  : [green]{out_path}[/green]")
    console.print(f"Stack   : [yellow]{stack}[/yellow]")
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task("Running static analysis...", total=None)
        analyser = AppAnalyzer(str(src_path))
        profile = analyser.analyse()
        progress.remove_task(task)

    # Print profile summary
    table = Table(title="Detected Application Profile", show_header=True)
    table.add_column("Component", style="cyan")
    table.add_column("Detected", style="white")
    table.add_row("Languages", ", ".join(profile.languages) or "—")
    table.add_row("Frameworks", ", ".join(profile.frameworks) or "—")
    table.add_row("Databases", ", ".join(profile.db_connections) or "—")
    table.add_row("Queues", ", ".join(profile.queues) or "—")
    table.add_row("External deps", ", ".join(profile.external_deps) or "—")
    table.add_row(
        "Endpoints",
        (str(len(profile.endpoints)) + " found") if profile.endpoints else "—",
    )
    console.print(table)
    console.print()

    # --- Agent run -------------------------------------------------------
    if not api_key:
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            console.print(
                "[bold red]ERROR:[/bold red] No Anthropic API key found. "
                "Set ANTHROPIC_API_KEY or pass --api-key."
            )
            sys.exit(1)

    agent = MonitorAgent(api_key=api_key, verbose=(not quiet))

    console.rule("[bold cyan]Running MonitorAgent[/bold cyan]")

    try:
        summary = agent.generate(src=str(src_path), output=str(out_path), stack=stack)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[bold red]Agent error:[/bold red] {exc}")
        sys.exit(1)

    # --- Output summary --------------------------------------------------
    console.rule("[bold green]Complete[/bold green]")

    if summary:
        console.print(Panel(Markdown(summary), title="Agent Summary", border_style="green"))

    _print_output_tree(out_path)


@cli.command()
@click.option(
    "--src",
    default=".",
    show_default=True,
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Path to the application source directory.",
)
def analyze(
    src: str,
) -> None:
    """Run only the static analyser (no AI call) and print the app profile."""
    src_path = Path(src).resolve()
    console.print(f"Analysing [green]{src_path}[/green] ...\n")
    analyser = AppAnalyzer(str(src_path))
    profile = analyser.analyse()
    console.print(profile.summary())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_output_tree(out_path: Path) -> None:
    """Print a summary of files written under out_path."""
    if not out_path.exists():
        console.print(f"[yellow]No output directory created at {out_path}[/yellow]")
        return

    files = sorted(out_path.rglob("*"))
    files = [f for f in files if f.is_file()]

    if not files:
        console.print("[yellow]No files were written.[/yellow]")
        return

    table = Table(title=f"Generated files in {out_path}", show_header=True)
    table.add_column("File", style="cyan")
    table.add_column("Size", justify="right")

    for f in files:
        size = f.stat().st_size
        size_str = f"{size:,} B" if size < 1024 else f"{size // 1024:,} KB"
        table.add_row(str(f.relative_to(out_path)), size_str)

    console.print(table)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
