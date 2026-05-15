"""Detección de ideas recurrentes → índice `recurring-themes.md` (T-405).

Una idea recurrente es un tema que reaparece en varias notas a lo largo del
tiempo. Para detectarlas:

1. **Clustering por componentes conexas.** Se construye un grafo donde cada
   nota es un nodo y hay arista entre dos notas con similitud coseno ≥
   `recurring_similarity_threshold` (vía los top-k vecinos de Qdrant, mismo
   patrón que T-404). Las componentes conexas — calculadas con union-find —
   son los clusters temáticos. Equivale a *single-linkage clustering*.
2. **Filtro de recurrencia.** Un cluster es una idea *recurrente* solo si
   tiene ≥ `recurring_min_notes` notas Y esas notas vienen de ≥
   `recurring_min_calls` llamadas distintas. Lo segundo es lo "temporal":
   varias notas de una sola llamada son una discusión puntual, no recurrencia.
3. **Nombrado.** El LLM pone nombre y resumen a cada cluster cualificado.

`build_recurring_themes_index()` agrega el resultado en
`vault/recurring-themes.md` (MOC en la raíz del Vault). Se regenera con
`enigma themes`; está pensado para correrse periódicamente (p.ej. semanal).
"""

import json
import logging
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import ollama
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from enigma.agent.prompts import build_theme_messages
from enigma.config import settings
from enigma.models.note import Note
from enigma.vault.reader import load_all_notes
from enigma.vault.writer import note_stem
from enigma.vector.embedder import embed_note
from enigma.vector.qdrant_client import search

_log = logging.getLogger(__name__)

MAX_LLM_RETRIES = 3
"""Reintentos cuando el LLM no devuelve JSON parseable/validable."""

_INDEX_FILENAME = "recurring-themes.md"
"""Nombre fijo del índice de ideas recurrentes, en la raíz del Vault."""


class ThemesError(RuntimeError):
    """El LLM falló al nombrar una idea recurrente."""


class ThemeMember(BaseModel):
    """Una nota que forma parte de una idea recurrente."""

    model_config = ConfigDict(extra="forbid")

    note_id: UUID
    title: str
    stem: str


class RecurringTheme(BaseModel):
    """Una idea recurrente detectada en el corpus."""

    model_config = ConfigDict(extra="forbid")

    name: str
    summary: str
    note_count: int
    call_count: int
    members: list[ThemeMember]


class ThemeIndexResult(BaseModel):
    """Resultado de `build_recurring_themes_index`: temas y métricas."""

    model_config = ConfigDict(extra="forbid")

    themes: list[RecurringTheme]
    notes_scanned: int
    clusters_found: int
    index_path: Path


class _ThemeVerdict(BaseModel):
    """Forma del JSON que devuelve el LLM al nombrar un cluster."""

    model_config = ConfigDict(extra="ignore")

    theme: str
    summary: str = ""


@lru_cache(maxsize=1)
def _client() -> ollama.Client:
    """Cliente Ollama cacheado, apuntando a `settings.ollama_host`."""
    return ollama.Client(host=settings.ollama_host)


class _UnionFind:
    """Estructura union-find (disjoint-set) con compresión de caminos.

    Sirve para calcular las componentes conexas del grafo de similitud sin
    una librería de grafos.
    """

    def __init__(self, items: list[UUID]) -> None:
        self._parent: dict[UUID, UUID] = {item: item for item in items}

    def find(self, node: UUID) -> UUID:
        """Devuelve el representante del conjunto de `node`."""
        root = node
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[node] != root:  # compresión de caminos
            self._parent[node], node = root, self._parent[node]
        return root

    def union(self, a: UUID, b: UUID) -> None:
        """Fusiona los conjuntos de `a` y `b`."""
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[root_a] = root_b


def cluster_notes(notes: list[Note]) -> list[list[Note]]:
    """Agrupa las notas en clusters temáticos (componentes conexas).

    Construye el grafo de similitud (aristas = vecinos Qdrant por encima de
    `recurring_similarity_threshold`) y calcula sus componentes conexas con
    union-find. Cada componente es un cluster; las notas sin vecinos forman
    un cluster de tamaño 1.
    """
    by_id = {note.id: note for note in notes}
    union_find = _UnionFind(list(by_id))

    for note in notes:
        vector = embed_note(note)
        # +1: la propia nota está indexada y aparecerá en sus vecinos.
        hits = search(vector, top_k=settings.recurring_top_k + 1)
        for hit in hits:
            same_or_unknown = hit.note_id == note.id or hit.note_id not in by_id
            if same_or_unknown or hit.score < settings.recurring_similarity_threshold:
                continue
            union_find.union(note.id, hit.note_id)

    groups: dict[UUID, list[Note]] = {}
    for note in notes:
        groups.setdefault(union_find.find(note.id), []).append(note)
    return list(groups.values())


def _format_notes_block(notes: list[Note]) -> str:
    """Formatea un cluster de notas para el prompt de nombrado."""
    return "\n\n".join(f"### {note.title}\n{note.body}" for note in notes)


def _request_theme(notes: list[Note], *, model: str) -> _ThemeVerdict:
    """Pide al LLM el nombre y resumen de un cluster (JSON, con reintentos).

    Raises:
        ThemesError: si tras `MAX_LLM_RETRIES` no hay JSON validable.
    """
    messages = build_theme_messages(_format_notes_block(notes))
    last_error: Exception | None = None
    for _attempt in range(MAX_LLM_RETRIES):
        try:
            response = _client().chat(
                model=model,
                messages=messages,
                format="json",
                options={"temperature": 0.2},
            )
            content = str(response["message"]["content"])
            return _ThemeVerdict.model_validate_json(content)
        except (json.JSONDecodeError, ValidationError, ollama.ResponseError, KeyError) as exc:
            last_error = exc
            continue
    raise ThemesError(
        f"El LLM no nombró el tema tras {MAX_LLM_RETRIES} intentos",
    ) from last_error


def name_theme(notes: list[Note], *, model: str | None = None) -> RecurringTheme:
    """Pide al LLM que nombre la idea recurrente de un cluster de notas.

    Raises:
        ThemesError: si el LLM falla al producir JSON válido.
    """
    verdict = _request_theme(notes, model=model or settings.ollama_llm_model)
    members = [
        ThemeMember(note_id=note.id, title=note.title, stem=note_stem(note.id, note.title))
        for note in notes
    ]
    call_ids = {note.source.call_id for note in notes}
    return RecurringTheme(
        name=verdict.theme,
        summary=verdict.summary,
        note_count=len(notes),
        call_count=len(call_ids),
        members=members,
    )


def _is_recurring(cluster: list[Note]) -> bool:
    """`True` si el cluster cumple el criterio de idea *recurrente*.

    Necesita ≥ `recurring_min_notes` notas y que provengan de ≥
    `recurring_min_calls` llamadas distintas (el componente temporal).
    """
    if len(cluster) < settings.recurring_min_notes:
        return False
    call_ids = {note.source.call_id for note in cluster}
    return len(call_ids) >= settings.recurring_min_calls


def render_themes_markdown(themes: list[RecurringTheme]) -> str:
    """Renderiza el índice `recurring-themes.md`.

    Los temas se listan ordenados por número de notas descendente; cada uno
    enlaza sus notas con `[[wikilink]]`.
    """
    frontmatter = {
        "type": "recurring-themes-index",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "theme_count": len(themes),
    }
    fm_block = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()

    if not themes:
        body = "_No se han detectado ideas recurrentes._"
        return f"---\n{fm_block}\n---\n\n# Ideas recurrentes\n\n{body}\n"

    sections: list[str] = []
    for theme in themes:
        links = "\n".join(f"- [[{m.stem}|{m.title}]]" for m in theme.members)
        sections.append(
            f"## {theme.name}\n\n{theme.summary}\n\n"
            f"Notas ({theme.note_count} en {theme.call_count} llamadas):\n\n{links}",
        )

    body = "\n\n".join(sections)
    return f"---\n{fm_block}\n---\n\n# Ideas recurrentes\n\n{body}\n"


def write_themes_index(
    themes: list[RecurringTheme],
    *,
    vault_path: Path | None = None,
) -> Path:
    """Persiste `recurring-themes.md` en la raíz del Vault. Idempotente."""
    root = vault_path if vault_path is not None else settings.enigma_vault_path
    root.mkdir(parents=True, exist_ok=True)
    target = root / _INDEX_FILENAME
    target.write_text(render_themes_markdown(themes), encoding="utf-8")
    return target


def build_recurring_themes_index(
    *,
    model: str | None = None,
    vault_path: Path | None = None,
) -> ThemeIndexResult:
    """Detecta las ideas recurrentes del Vault y reescribe `recurring-themes.md`.

    Clusteriza las notas, conserva los clusters que cumplen el criterio de
    recurrencia y pide al LLM un nombre para cada uno. Un fallo del LLM en un
    cluster se omite con un warning.

    Returns:
        `ThemeIndexResult` con los temas y métricas de la pasada.
    """
    notes = load_all_notes(vault_path)
    clusters = cluster_notes(notes)

    themes: list[RecurringTheme] = []
    for cluster in clusters:
        if not _is_recurring(cluster):
            continue
        try:
            themes.append(name_theme(cluster, model=model))
        except ThemesError:
            _log.warning("Nombrado de un cluster recurrente falló; se omite")
            continue

    themes.sort(key=lambda theme: theme.note_count, reverse=True)
    index_path = write_themes_index(themes, vault_path=vault_path)
    _log.info(
        "Índice de ideas recurrentes: %d temas de %d clusters (%d notas) → %s",
        len(themes),
        len(clusters),
        len(notes),
        index_path,
    )
    return ThemeIndexResult(
        themes=themes,
        notes_scanned=len(notes),
        clusters_found=len(clusters),
        index_path=index_path,
    )
