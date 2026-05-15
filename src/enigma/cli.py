"""Entrypoint Typer del comando `enigma`.

Expone:
- `enigma --version` / `enigma -v` → imprime la versión y sale.
- `enigma version` → mismo resultado, como subcomando.
- `enigma ingest <audio> [--title T]` → pipeline end-to-end (T-113).
- `enigma list calls` → tabla de llamadas registradas (T-114).
- `enigma list notes [--last 7d]` → tabla de notas del Vault (T-114).

Subcomandos adicionales (ask, etc.) se añaden en fases posteriores y se
enganchan al `app` global definido aquí.
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from enigma import __version__

app = typer.Typer(
    name="enigma",
    help="Enigma — segundo cerebro conversacional local-first.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    """Callback del flag `--version`: imprime versión y termina."""
    if value:
        typer.echo(f"enigma {__version__}")
        raise typer.Exit


@app.callback()
def main(
    show_version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-v",
            callback=_version_callback,
            is_eager=True,
            help="Mostrar la versión y salir.",
        ),
    ] = False,
) -> None:
    """Enigma — segundo cerebro conversacional local-first para equipos pequeños."""


@app.command()
def version() -> None:
    """Mostrar la versión instalada de Enigma."""
    typer.echo(f"enigma {__version__}")


@app.command()
def ingest(
    audio_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Ruta al fichero de audio (.wav/.mp3/.m4a/.ogg).",
        ),
    ],
    title: Annotated[
        str | None,
        typer.Option(
            "--title",
            "-t",
            help="Título opcional de la llamada.",
        ),
    ] = None,
) -> None:
    """Procesa un audio end-to-end y vuelca las notas en el Vault.

    Cadena: registrar Call → transcribir → extraer notas atómicas →
    escribir en `<vault>/inbox/` + crear nota índice en `<vault>/calls/`.
    """
    from rich.console import Console

    from enigma.pipeline import ingest_audio

    console = Console()
    step_counter = [0]

    def echo_step(msg: str) -> None:
        step_counter[0] += 1
        console.print(f"[bold cyan][{step_counter[0]}/4][/bold cyan] {msg}…")

    try:
        result = ingest_audio(audio_path, title=title, on_step=echo_step)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print()
    console.print(f"[green]✓[/green] Llamada [bold]{result.call.id}[/bold] procesada.")
    console.print(f"  • {len(result.notes)} nota(s) extraída(s).")
    if result.note_paths:
        console.print(f"  • Notas: {result.note_paths[0].parent}")
    console.print(f"  • Índice de llamada: {result.call_index_path}")


@app.command()
def watch() -> None:
    """Observa el Vault y re-vectoriza notas al detectar cambios (Ctrl-C para parar)."""
    from rich.console import Console

    from enigma.workers.watcher import run_watcher

    Console().print(
        "[bold]Watcher activo.[/bold] Observando el Vault… (Ctrl-C para parar)",
    )
    run_watcher()


@app.command()
def orphans() -> None:
    """Marca con #orphan las notas del Vault sin wikilinks y reporta el conteo."""
    from rich.console import Console

    from enigma.vault.linker import mark_orphans

    console = Console()
    report = mark_orphans()
    console.print(f"Notas en el Vault:         {report.total_notes}")
    console.print(f"Huérfanas (sin wikilinks): [yellow]{report.orphans}[/yellow]")
    console.print(f"Recién marcadas #orphan:   {report.newly_tagged}")


# ── enigma list ─────────────────────────────────────────────────────────────

_LAST_WINDOW_RE = re.compile(r"^(\d+)\s*([dhwm])$")
_UNIT_TO_KWARG = {"d": "days", "h": "hours", "w": "weeks", "m": "minutes"}

list_app = typer.Typer(help="Listar llamadas y notas.", no_args_is_help=True)
app.add_typer(list_app, name="list")


def _parse_last_window(spec: str) -> timedelta:
    """Parsea `'7d'`, `'24h'`, `'2w'`, `'30m'` a `timedelta`.

    Raises:
        typer.BadParameter: si el formato no casa con `N` + `d/h/w/m`.
    """
    match = _LAST_WINDOW_RE.match(spec.strip().lower())
    if match is None:
        raise typer.BadParameter(
            f"Formato inválido: {spec!r}. Usa N seguido de d/h/w/m (p.ej. '7d').",
        )
    amount, unit = int(match.group(1)), match.group(2)
    return timedelta(**{_UNIT_TO_KWARG[unit]: amount})


@list_app.command("calls")
def list_calls_command() -> None:
    """Lista las llamadas registradas en SQLite."""
    from rich.console import Console
    from rich.table import Table

    from enigma.db import calls as calls_db
    from enigma.db.sqlite import get_connection

    console = Console()
    with get_connection() as conn:
        calls = calls_db.list_calls(conn)

    if not calls:
        console.print("[yellow]No hay llamadas registradas.[/yellow]")
        return

    table = Table(title=f"Llamadas ({len(calls)})")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Título")
    table.add_column("Grabada")
    table.add_column("Duración")
    table.add_column("Estado")
    for call in calls:
        table.add_row(
            call.id.hex[:8],
            call.title or "—",
            call.recorded_at.strftime("%Y-%m-%d %H:%M"),
            f"{call.duration_seconds / 60:.1f} min",
            call.status,
        )
    console.print(table)


@list_app.command("notes")
def list_notes_command(
    last: Annotated[
        str | None,
        typer.Option(
            "--last",
            help="Ventana temporal: N seguido de d/h/w/m (p.ej. '7d').",
        ),
    ] = None,
) -> None:
    """Lista las notas del Vault, opcionalmente filtradas por antigüedad."""
    from rich.console import Console
    from rich.table import Table

    from enigma.vault.reader import list_vault_notes

    console = Console()
    since = datetime.now(tz=UTC) - _parse_last_window(last) if last is not None else None
    notes = list_vault_notes(since=since)

    if not notes:
        suffix = f" en los últimos {last}." if last else " en el Vault."
        console.print(f"[yellow]No hay notas{suffix}[/yellow]")
        return

    table = Table(title=f"Notas ({len(notes)})")
    table.add_column("Creada", style="cyan", no_wrap=True)
    table.add_column("Título")
    table.add_column("Estado")
    table.add_column("Tags")
    for note in notes:
        table.add_row(
            note.created_at.strftime("%Y-%m-%d %H:%M"),
            note.title,
            note.status,
            ", ".join(note.tags) or "—",
        )
    console.print(table)


if __name__ == "__main__":
    app()
