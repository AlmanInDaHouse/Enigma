"""Meta-test de onboarding de Enigma (T-506).

Ejecuta el pipeline COMPLETO sobre un audio de una sesión de onboarding y
comprueba, etapa por etapa, que todo el sistema funciona de extremo a extremo:

    ingest → reindex → ask (RAG) → decisions → tasks → themes → summarize

Es el "meta-test definitivo": Enigma procesando su propia sesión de onboarding.
Está pensado para correrse con la grabación real del equipo, pero funciona con
cualquier audio (incluido el sintético de `generate_onboarding_audio.ps1`).

Uso:
    uv run python scripts/onboarding_metatest.py [ruta-al-audio]

Default del audio: data/audio/onboarding_sintetico.wav

Sale con código 0 si las etapas críticas (ingest, reindex, ask) pasan; 1 si
alguna falla. Las etapas analíticas (decisions/tasks/themes/summarize) se
reportan con sus conteos como evidencia; que encuentren 0 elementos no es un
fallo del pipeline (p.ej. los temas recurrentes necesitan varias llamadas).
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar
from uuid import UUID

from enigma.agent.decisions import build_decision_index
from enigma.agent.rag import NO_CONTEXT_ANSWER, RagAnswer, answer_question
from enigma.agent.summarizer import summarize_call
from enigma.agent.tasks_extractor import build_task_index
from enigma.agent.themes import build_recurring_themes_index
from enigma.pipeline import IngestResult, ingest_audio
from enigma.vector.reindexer import reindex_vault

# El informe usa caracteres no-ASCII (→, 🪞); en Windows, si la salida se
# redirige a un fichero, su codificación puede ser cp1252 y romper. Forzar
# UTF-8 lo evita. Debe ejecutarse antes del primer `print`.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

_T = TypeVar("_T")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_AUDIO = _REPO_ROOT / "data" / "audio" / "onboarding_sintetico.wav"

_QUESTIONS = [
    "¿Cada cuánto hay que revisar el inbox?",
    "¿Quién se encarga de la guía de usuario?",
    "¿Enigma envía las grabaciones a servicios externos?",
]


class _Stage:
    """Acumula el resultado de una etapa del meta-test."""

    def __init__(self, name: str, *, critical: bool) -> None:
        self.name = name
        self.critical = critical
        self.passed = False
        self.detail = ""

    def check(self, *, passed: bool, detail: str) -> None:
        """Marca el resultado de la etapa y lo imprime."""
        self.passed = passed
        self.detail = detail
        print(f"  [{'PASS' if passed else 'FAIL'}] {detail}", flush=True)


def _run(stage: _Stage, fn: Callable[[], _T]) -> _T | None:
    """Ejecuta `fn`, cronometra y devuelve su resultado (o `None` si falla)."""
    print(f"\n--- {stage.name} ---", flush=True)
    start = time.perf_counter()
    try:
        result = fn()
    except Exception as exc:  # un fallo de cualquier etapa = etapa fallida
        stage.check(passed=False, detail=f"EXCEPCIÓN: {exc}")
        return None
    print(f"  ({time.perf_counter() - start:.1f}s)", flush=True)
    return result


def _ask_questions() -> _Stage:
    """Etapa de RAG: lanza varias preguntas y comprueba que se responden."""
    stage = _Stage("3. ask — RAG con citas", critical=True)

    def _ask_all() -> list[RagAnswer]:
        answers: list[RagAnswer] = []
        for question in _QUESTIONS:
            answer = answer_question(question)
            print(f"  P: {question}")
            print(f"  R: {answer.answer}")
            print(f"     citas: {len(answer.citations)}")
            answers.append(answer)
        return answers

    answers = _run(stage, _ask_all)
    if answers is None:
        return stage
    useful = [a for a in answers if a.answer and a.answer != NO_CONTEXT_ANSWER]
    cited = sum(len(a.citations) for a in answers)
    stage.check(
        passed=len(useful) > 0,
        detail=f"{len(useful)}/{len(_QUESTIONS)} respuestas con contexto; {cited} cita(s)",
    )
    return stage


def _run_critical_stages(audio: Path) -> tuple[list[_Stage], IngestResult | None]:
    """Etapas críticas: ingest → reindex → ask. Devuelve (stages, ingest_result)."""
    ingest = _Stage("1. ingest — audio → notas", critical=True)
    result = _run(ingest, lambda: ingest_audio(audio, title="Onboarding de Enigma"))
    if result is None:
        return [ingest], None
    ingest.check(
        passed=len(result.notes) > 0 and result.call_index_path.is_file(),
        detail=f"{len(result.notes)} nota(s); índice {result.call_index_path.name}",
    )
    if not ingest.passed:
        return [ingest], None

    reindex = _Stage("2. reindex — notas → Qdrant", critical=True)
    report = _run(reindex, reindex_vault)
    if report is not None:
        reindex.check(
            passed=report.collection_points > 0,
            detail=f"{report.collection_points} vector(es) en Qdrant",
        )

    return [ingest, reindex, _ask_questions()], result


def _run_analytic_stages(call_id: UUID) -> list[_Stage]:
    """Etapas analíticas: decisions → tasks → themes → summarize."""
    decisions = _Stage("4. decisions — índice de decisiones", critical=False)
    dec = _run(decisions, build_decision_index)
    if dec is not None:
        decisions.check(
            passed=dec.index_path.is_file(),
            detail=f"{len(dec.decisions)} decisión(es) → {dec.index_path.name}",
        )

    tasks = _Stage("5. tasks — índice de tareas", critical=False)
    tsk = _run(tasks, build_task_index)
    if tsk is not None:
        tasks.check(
            passed=tsk.index_path.is_file(),
            detail=f"{len(tsk.tasks)} tarea(s) → {tsk.index_path.name}",
        )

    themes = _Stage("6. themes — ideas recurrentes", critical=False)
    thm = _run(themes, build_recurring_themes_index)
    if thm is not None:
        themes.check(
            passed=thm.index_path.is_file(),
            detail=f"{len(thm.themes)} tema(s) de {thm.clusters_found} cluster(s)",
        )

    summary = _Stage("7. summarize — resumen de la llamada", critical=False)
    res = _run(summary, lambda: summarize_call(call_id))
    if res is not None:
        summary.check(
            passed=res.summary_path.is_file(),
            detail=f"resumen → {res.summary_path.name}",
        )

    return [decisions, tasks, themes, summary]


def _report(stages: list[_Stage]) -> int:
    """Imprime el informe final y devuelve el código de salida."""
    print("\n" + "=" * 70)
    print("INFORME DEL META-TEST")
    print("=" * 70)
    for stage in stages:
        mark = "PASS" if stage.passed else "FAIL"
        tag = "crítica" if stage.critical else "analítica"
        print(f"  [{mark}] ({tag}) {stage.name} — {stage.detail}")

    if any(s.critical and not s.passed for s in stages):
        print("\nRESULTADO: FALLO — alguna etapa crítica no pasó.")
        return 1
    print("\nRESULTADO: OK — Enigma procesó su onboarding de extremo a extremo. 🪞")
    return 0


def main(argv: list[str]) -> int:
    audio = Path(argv[1]) if len(argv) > 1 else _DEFAULT_AUDIO
    if not audio.is_file():
        print(f"[ERROR] No se encuentra el audio: {audio}")
        print("Genera uno con: scripts\\generate_onboarding_audio.ps1")
        return 1

    print("=" * 70)
    print("META-TEST DE ONBOARDING DE ENIGMA (T-506)")
    print(f"Audio: {audio}")
    print("=" * 70)

    critical_stages, ingest_result = _run_critical_stages(audio)
    stages = list(critical_stages)
    if ingest_result is not None:
        stages.extend(_run_analytic_stages(ingest_result.call.id))
    return _report(stages)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
