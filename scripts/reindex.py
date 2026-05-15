"""Reconstruye la colección Qdrant desde el Vault de Obsidian (T-203).

Vectoriza todas las notas de `vault/inbox/` y `vault/notes/` y las upsertea
en Qdrant. Idempotente: reejecutar no duplica puntos.

Uso:
    uv run python scripts/reindex.py

Requiere Qdrant corriendo (`docker compose up -d qdrant`) y Ollama con
`nomic-embed-text` disponible.
"""

from rich.console import Console

from enigma.vector.reindexer import reindex_vault


def main() -> None:
    """Lanza el reindexado e imprime el informe de métricas."""
    console = Console()
    console.print("[bold]Reindexando el Vault en Qdrant…[/bold]")

    report = reindex_vault()

    console.print()
    console.print(f"[green]✓[/green] {report.notes_indexed} nota(s) vectorizada(s).")
    console.print(f"  • Tiempo total:   {report.elapsed_seconds:.2f} s")
    console.print(f"  • Velocidad:      {report.notes_per_second:.1f} notas/s")
    console.print(f"  • Dim. de vector: {report.vector_dim}")
    console.print(f"  • Puntos Qdrant:  {report.collection_points}")


if __name__ == "__main__":
    main()
