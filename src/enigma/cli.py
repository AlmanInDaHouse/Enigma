"""Entrypoint Typer del comando `enigma`.

Expone:
- `enigma --version` / `enigma -v` → imprime la versión y sale.
- `enigma version` → mismo resultado, como subcomando.
- `enigma ingest <audio> [--title T]` → pipeline end-to-end (T-113).

Subcomandos adicionales (list, ask, etc.) se añaden en fases posteriores
y se enganchan al `app` global definido aquí.
"""

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


if __name__ == "__main__":
    app()
