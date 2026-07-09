"""Pipeline CLI — run, review HITL gates, resume."""

import asyncio
import json
import time

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from calllens.config import settings
from calllens.agents.graph import (
    run_pipeline, resume_pipeline, get_pipeline_state,
    make_batch_id, PipelineInterrupted,
)

console = Console()


@click.group()
def pipeline():
    """CalLens agent pipeline commands."""
    pass


@pipeline.command()
@click.option("--tenant-id", default=lambda: str(settings.default_tenant_id))
@click.option("--batch-id", default=None, help="Explicit batch ID (for resume).")
@click.option("--fresh", is_flag=True, help="Force a brand-new run ignoring any checkpoint.")
def run(tenant_id: str, batch_id: str | None, fresh: bool):
    """Run the full pipeline (or resume an interrupted run)."""
    if fresh:
        resolved = f"fresh-{int(time.time())}"
    else:
        resolved = batch_id or make_batch_id(tenant_id)

    console.print(
        f"[bold]Pipeline run[/bold] — "
        f"tenant=[cyan]{tenant_id}[/cyan]  batch=[cyan]{resolved}[/cyan]"
    )
    try:
        result = asyncio.run(run_pipeline(tenant_id, resolved))
        _print_summary(result)
    except PipelineInterrupted as exc:
        _print_interrupted(exc)
    except Exception as exc:
        console.print(f"[red]Pipeline error:[/red] {exc}")
        raise


@pipeline.command()
@click.option("--tenant-id", default=lambda: str(settings.default_tenant_id))
@click.option("--batch-id", required=True)
def review(tenant_id: str, batch_id: str):
    """Show pending HITL data for an interrupted batch."""
    state = asyncio.run(get_pipeline_state(batch_id))
    if not state["next"]:
        console.print("[green]This batch has completed — nothing pending.[/green]")
        return

    console.print(f"[yellow]Paused at:[/yellow] {state['next']}")
    for item in state["interrupt_data"]:
        console.print_json(json.dumps(item, indent=2, default=str))

    _print_resume_hint(batch_id, state["interrupt_data"])


@pipeline.command()
@click.option("--tenant-id", default=lambda: str(settings.default_tenant_id))
@click.option("--batch-id", required=True)
@click.option(
    "--approve-all", is_flag=True,
    help="Approve all pending risk signals without review (for testing).",
)
@click.option(
    "--corrections", default=None,
    help="JSON resume value — list of account names to approve, or classification corrections.",
)
def resume(tenant_id: str, batch_id: str, approve_all: bool, corrections: str | None):
    """Resume a paused pipeline with human input."""
    if approve_all:
        # Fetch pending state to get account names, then approve all
        state = asyncio.run(get_pipeline_state(batch_id))
        risks = state["values"].get("risks", [])
        resume_value = [r["account_name"] for r in risks]
        console.print(f"[yellow]Auto-approving {len(resume_value)} accounts.[/yellow]")
    elif corrections:
        try:
            resume_value = json.loads(corrections)
        except json.JSONDecodeError as exc:
            console.print(f"[red]Invalid JSON for --corrections:[/red] {exc}")
            return
    else:
        console.print("[red]Provide --approve-all or --corrections JSON.[/red]")
        return

    console.print(f"[bold]Resuming[/bold] batch=[cyan]{batch_id}[/cyan]")
    try:
        result = asyncio.run(resume_pipeline(tenant_id, batch_id, resume_value))
        _print_summary(result)
    except PipelineInterrupted as exc:
        _print_interrupted(exc)
    except Exception as exc:
        console.print(f"[red]Resume error:[/red] {exc}")
        raise


# ── Display helpers ────────────────────────────────────────────────────────

def _print_interrupted(exc: PipelineInterrupted) -> None:
    console.print(f"\n[yellow bold]Pipeline paused — HITL gate: {exc.pending_node}[/yellow bold]")
    console.print(f"Batch ID: [cyan]{exc.batch_id}[/cyan]")

    for item in exc.interrupt_data:
        if isinstance(item, dict) and item.get("type") == "risk_review":
            risks = item.get("risks", [])
            console.print(f"\n[bold]Risks requiring approval ({len(risks)}):[/bold]")
            for r in risks:
                console.print(
                    f"  [{r['risk_level']}] [bold]{r['account_name']}[/bold]  "
                    f"signals: {', '.join(r.get('signal_types', []))}"
                )
        elif isinstance(item, dict) and item.get("type") == "classification_review":
            uncertain = item.get("uncertain_calls", {})
            console.print(f"\n[bold]Uncertain classifications ({len(uncertain)}):[/bold]")
            for call_id, c in uncertain.items():
                console.print(f"  {call_id[:8]}  conf={c['confidence']:.2f}  {c['call_type']}")

    console.print(
        Panel(
            f"[bold]To approve all and resume:[/bold]\n"
            f"  calllens-pipeline resume --batch-id {exc.batch_id} --approve-all\n\n"
            f"[bold]To approve specific accounts:[/bold]\n"
            f'  calllens-pipeline resume --batch-id {exc.batch_id} '
            f'--corrections \'["Account A", "Account B"]\'',
            title="Next steps",
        )
    )


def _print_resume_hint(batch_id: str, interrupt_data: list) -> None:
    console.print(
        f"\nTo resume: [bold]calllens-pipeline resume --batch-id {batch_id} --approve-all[/bold]"
    )


def _print_summary(result: dict) -> None:
    console.print("\n[bold green]Pipeline complete[/bold green]")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Stage", style="cyan")
    table.add_column("Count", justify="right")
    table.add_row("Calls loaded",       str(len(result.get("calls_data", []))))
    table.add_row("Classifications",    str(len(result.get("classifications", []))))
    table.add_row("Topic clusters",     str(len(result.get("topics", []))))
    table.add_row("Risk signals",       str(len(result.get("risks", []))))
    table.add_row("Insights generated", str(len(result.get("insights", []))))
    table.add_row("Errors",             str(len(result.get("errors", []))))
    console.print(table)

    if result.get("errors"):
        console.print("\n[yellow]Errors:[/yellow]")
        for e in result["errors"]:
            console.print(f"  [dim]{e.get('stage')}[/dim]  {str(e.get('message', ''))[:120]}")

    if result.get("topics"):
        console.print("\n[bold]Top topics:[/bold]")
        for t in sorted(result["topics"], key=lambda x: -x.get("frequency", 0))[:8]:
            console.print(f"  • {t['canonical_name']}  ({t.get('frequency', '?')} calls)")

    if result.get("risks"):
        console.print("\n[bold]Risk signals:[/bold]")
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for r in sorted(result["risks"], key=lambda x: order.get(x.get("risk_level", "low"), 3)):
            icon = "✓" if r.get("approved") else "⏳"
            console.print(f"  {icon} [{r['risk_level']}] {r['account_name']}")

    if result.get("insights"):
        console.print("\n[bold]Insights by persona:[/bold]")
        from collections import Counter
        counts = Counter(i["persona"] for i in result["insights"])
        for persona, count in sorted(counts.items()):
            console.print(f"  • {persona}: {count}")
        console.print()
        console.print("[bold]Sample insights:[/bold]")
        for ins in result["insights"][:3]:
            console.print(
                f"  [{ins.get('severity','?')}] [bold]{ins['title']}[/bold]\n"
                f"    {ins['body'][:120]}..."
            )
