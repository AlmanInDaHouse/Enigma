"""Entrypoint Typer del comando `enigma`.

Expone:
- `enigma --version` / `enigma -v` → imprime la versión y sale.
- `enigma version` → mismo resultado, como subcomando.
- `enigma ingest <audio> [--title T]` → pipeline end-to-end (T-113).
- `enigma list calls` → tabla de llamadas registradas (T-114).
- `enigma list notes [--last 7d]` → tabla de notas del Vault (T-114).
- `enigma search "<query>"` → notas top-k por similitud semántica (T-301).
- `enigma ask "<pregunta>"` → respuesta RAG con citas (T-303).
- `enigma serve` → arranca la API REST (`POST /ask`) con uvicorn (T-305).
- `enigma summarize call <id>` → resumen ejecutivo de una llamada (T-401).
- `enigma decisions` → regenera el índice de decisiones del corpus (T-402).
- `enigma tasks` → regenera el índice de tareas pendientes del corpus (T-403).
- `enigma contradictions` → regenera el índice de contradicciones (T-404).

Subcomandos adicionales se añaden en fases posteriores y se enganchan al
`app` global definido aquí.
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from uuid import UUID

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


@app.command()
def search(
    query: Annotated[
        str,
        typer.Argument(help="Consulta en lenguaje natural."),
    ],
    top_k: Annotated[
        int,
        typer.Option(
            "--top-k",
            "-k",
            min=1,
            help="Número de notas a recuperar.",
        ),
    ] = 5,
) -> None:
    """Busca notas del Vault por similitud semántica (RF-07)."""
    from rich.console import Console
    from rich.table import Table

    from enigma.search import search_notes

    console = Console()
    if not query.strip():
        raise typer.BadParameter("La consulta no puede estar vacía.")

    results = search_notes(query, top_k=top_k)
    if not results:
        console.print("[yellow]Sin resultados para esa consulta.[/yellow]")
        return

    table = Table(title=f"Resultados ({len(results)})")
    table.add_column("#", style="dim", no_wrap=True)
    table.add_column("Score", style="cyan", no_wrap=True)
    table.add_column("Título")
    table.add_column("Tags")
    table.add_column("Creada", no_wrap=True)
    for rank, result in enumerate(results, start=1):
        created = result.created_at.strftime("%Y-%m-%d %H:%M") if result.created_at else "—"
        table.add_row(
            str(rank),
            f"{result.score:.3f}",
            result.title,
            ", ".join(result.tags) or "—",
            created,
        )
    console.print(table)


@app.command()
def ask(
    question: Annotated[
        str,
        typer.Argument(help="Pregunta en lenguaje natural sobre el Vault."),
    ],
    top_k: Annotated[
        int,
        typer.Option(
            "--top-k",
            "-k",
            min=1,
            help="Número de notas a usar como contexto.",
        ),
    ] = 5,
) -> None:
    """Responde una pregunta con RAG sobre el Vault, citando las notas (T-303)."""
    from rich.console import Console
    from rich.panel import Panel

    from enigma.agent.rag import RagError, answer_question

    console = Console()
    if not question.strip():
        raise typer.BadParameter("La pregunta no puede estar vacía.")

    try:
        result = answer_question(question, top_k=top_k)
    except RagError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print()
    console.print(Panel(result.answer, title="Respuesta", border_style="cyan"))

    if result.citations:
        console.print("\n[bold]Notas citadas:[/bold]")
        for citation in result.citations:
            # markup=False: los corchetes de `[[wikilink]]` son literales,
            # no markup de Rich.
            console.print(f"  • [[{citation.stem}]] — {citation.title}", markup=False)
    else:
        console.print("\n[yellow]La respuesta no cita ninguna nota del Vault.[/yellow]")


@app.command()
def serve(
    host: Annotated[
        str | None,
        typer.Option("--host", help="Host de escucha. Default `settings.api_host`."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Puerto de escucha. Default `settings.api_port`."),
    ] = None,
) -> None:
    """Arranca la API REST de Enigma (endpoint `POST /ask`) con uvicorn (T-305)."""
    import uvicorn
    from rich.console import Console

    from enigma.config import settings

    effective_host = host or settings.api_host
    effective_port = port or settings.api_port

    Console().print(
        f"[bold]API de Enigma[/bold] escuchando en "
        f"http://{effective_host}:{effective_port} (Ctrl-C para parar)",
    )
    uvicorn.run(
        "enigma.api:app",
        host=effective_host,
        port=effective_port,
        log_level=settings.api_log_level,
    )


# ── enigma summarize ────────────────────────────────────────────────────────

summarize_app = typer.Typer(help="Generar resúmenes con el agente.", no_args_is_help=True)
app.add_typer(summarize_app, name="summarize")


def _resolve_call_id(id_or_prefix: str) -> UUID:
    """Resuelve un UUID completo o un prefijo hex corto a un `call_id`.

    `enigma list calls` muestra los 8 primeros hex del id; este helper acepta
    ese prefijo (o cualquier prefijo, o el UUID completo).

    Raises:
        typer.BadParameter: si no hay ninguna coincidencia o si hay varias.
    """
    from enigma.db import calls as calls_db
    from enigma.db.sqlite import get_connection

    with get_connection() as conn:
        all_calls = calls_db.list_calls(conn)

    needle = id_or_prefix.strip().lower().replace("-", "")
    matches = [call for call in all_calls if call.id.hex.startswith(needle)]

    if not matches:
        raise typer.BadParameter(f"Ninguna llamada con id/prefijo {id_or_prefix!r}.")
    if len(matches) > 1:
        ids = ", ".join(call.id.hex[:8] for call in matches)
        raise typer.BadParameter(
            f"Prefijo {id_or_prefix!r} ambiguo: coincide con {ids}. Usa más caracteres.",
        )
    return matches[0].id


@summarize_app.command("call")
def summarize_call_command(
    call_id: Annotated[
        str,
        typer.Argument(help="ID de la llamada (UUID completo o prefijo corto)."),
    ],
) -> None:
    """Genera el resumen ejecutivo de una llamada en `vault/calls/` (T-401)."""
    from rich.console import Console

    from enigma.agent.summarizer import SummarizationError, summarize_call

    console = Console()
    resolved = _resolve_call_id(call_id)

    try:
        result = summarize_call(resolved)
    except SummarizationError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]✓[/green] Resumen de la llamada [bold]{resolved}[/bold] generado.")
    console.print(f"  • TL;DR: {result.summary.tldr}")
    console.print(f"  • {len(result.summary.key_points)} punto(s) clave.")
    console.print(f"  • Nota: {result.summary_path}")


@app.command()
def decisions() -> None:
    """Regenera `vault/decisions.md`: índice de decisiones del corpus (T-402)."""
    from rich.console import Console

    from enigma.agent.decisions import DecisionsError, build_decision_index

    console = Console()
    try:
        result = build_decision_index()
    except DecisionsError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print("[green]✓[/green] Índice de decisiones regenerado.")
    console.print(f"  • Llamadas escaneadas:    {result.calls_scanned}")
    console.print(f"  • Llamadas con decisiones: {result.calls_with_decisions}")
    console.print(f"  • Decisiones totales:      [bold]{len(result.decisions)}[/bold]")
    console.print(f"  • Índice: {result.index_path}")


@app.command()
def tasks() -> None:
    """Regenera `vault/tasks.md`: índice de tareas pendientes del corpus (T-403)."""
    from rich.console import Console

    from enigma.agent.tasks_extractor import TasksError, build_task_index

    console = Console()
    try:
        result = build_task_index()
    except TasksError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print("[green]✓[/green] Índice de tareas regenerado.")
    console.print(f"  • Llamadas escaneadas:  {result.calls_scanned}")
    console.print(f"  • Llamadas con tareas:  {result.calls_with_tasks}")
    console.print(f"  • Tareas totales:       [bold]{len(result.tasks)}[/bold]")
    console.print(f"  • Índice: {result.index_path}")


@app.command()
def contradictions() -> None:
    """Regenera `vault/contradictions.md`: contradicciones entre notas (T-404)."""
    from rich.console import Console

    from enigma.agent.contradictions import build_contradiction_index

    console = Console()
    console.print("Buscando contradicciones… (puede tardar según el tamaño del Vault)")
    result = build_contradiction_index()

    console.print("[green]✓[/green] Índice de contradicciones regenerado.")
    console.print(f"  • Notas escaneadas:      {result.notes_scanned}")
    console.print(f"  • Pares evaluados:       {result.pairs_evaluated}")
    console.print(f"  • Contradicciones:       [bold]{len(result.contradictions)}[/bold]")
    console.print(f"  • Índice: {result.index_path}")


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
