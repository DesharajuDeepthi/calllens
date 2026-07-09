"""CLI: ingest call folders into Postgres — incremental by content hash."""

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from calllens.config import settings
from calllens.db import get_pool, close_pool, tenant_conn
from calllens.ingestion.parser import parse_call_folder
from calllens.ingestion.writer import write_call

console = Console()


async def _run_ingest(data_path: Path, tenant_id_str: str) -> None:
    from uuid import UUID
    tenant_id = UUID(tenant_id_str)

    folders = sorted([d for d in data_path.iterdir() if d.is_dir()])
    if not folders:
        console.print(f"[red]No call folders found in {data_path}[/red]")
        return

    console.print(
        f"[bold]CalLens Ingestion[/bold] — "
        f"{len(folders)} folders → tenant [cyan]{tenant_id_str}[/cyan]"
    )

    # Load all known content hashes in one query to avoid N round-trips
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT meeting_id, content_hash FROM calls WHERE tenant_id = $1",
            tenant_id,
        )
    known_hashes: dict[str, str] = {r["meeting_id"]: r["content_hash"] for r in rows}

    new_count = updated = skipped = errors = 0
    error_log: list[tuple[str, str]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning...", total=len(folders))

        for folder in folders:
            progress.update(task, description=f"[dim]{folder.name}[/dim]")
            try:
                parsed = parse_call_folder(folder)
                meeting_id = parsed.meeting_info.meeting_id
                known_hash = known_hashes.get(meeting_id)

                # Fast path: hash matches → nothing changed, skip entirely
                if known_hash == parsed.content_hash:
                    skipped += 1
                    progress.advance(task)
                    continue

                is_new = known_hash is None

                async with tenant_conn(tenant_id) as conn:
                    async with conn.transaction():
                        await write_call(conn, parsed, tenant_id)

                if is_new:
                    new_count += 1
                else:
                    updated += 1

            except Exception as exc:
                errors += 1
                error_log.append((folder.name, str(exc)))
            finally:
                progress.advance(task)

    await close_pool()

    console.print()
    console.print(f"[green]  New:[/green]      {new_count}")
    console.print(f"[blue]  Updated:[/blue]   {updated}")
    console.print(f"[yellow]  Skipped:[/yellow]   {skipped}  [dim](unchanged)[/dim]")
    console.print(f"[red]  Errors:[/red]    {errors}")

    if error_log:
        console.print("\n[red]Errors:[/red]")
        for name, msg in error_log:
            console.print(f"  [dim]{name}[/dim] → {msg}")


@click.command()
@click.option(
    "--data-path",
    default=lambda: settings.transcript_data_path,
    show_default=True,
    help="Path to the folder containing call sub-folders.",
)
@click.option(
    "--tenant-id",
    default=lambda: str(settings.default_tenant_id),
    show_default=True,
    help="Tenant UUID to associate all calls with.",
)
def ingest(data_path: str, tenant_id: str) -> None:
    """
    Ingest call folders into Postgres.

    Incremental — only NEW or CHANGED folders touch the database.
    Unchanged folders (same content hash) are skipped entirely.
    Safe to re-run at any time.
    """
    asyncio.run(_run_ingest(Path(data_path), tenant_id))
