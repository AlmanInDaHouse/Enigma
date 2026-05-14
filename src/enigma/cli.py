"""Entrypoint Typer del comando `enigma`.

Expone:
- `enigma --version` / `enigma -v` → imprime la versión y sale.
- `enigma version` → mismo resultado, como subcomando.

Subcomandos adicionales (ingest, list, ask, etc.) se añaden en fases
posteriores y se enganchan al `app` global definido aquí.
"""

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


if __name__ == "__main__":
    app()
