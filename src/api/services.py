"""Servicios de la API: análisis de casos, persistencia y jobs batch."""

import asyncio
import logging
import threading
import uuid
from typing import Any

import psycopg2
import psycopg2.extras

from src.rules.repository import DB_CONFIG
from src.utils.jsonb import jsonb

logger = logging.getLogger(__name__)

# Grafo compilado una sola vez (lo inicializa main.py en el lifespan)
_graph = None


def set_graph(graph: Any) -> None:
    """Registra el grafo compilado para los endpoints de análisis."""
    global _graph
    _graph = graph


def get_graph() -> Any:
    """Devuelve el grafo compilado (None si no se inicializó)."""
    return _graph


def conectar() -> psycopg2.extensions.connection:
    """Abre una conexión a PostgreSQL con dict cursor."""
    return psycopg2.connect(cursor_factory=psycopg2.extras.RealDictCursor, **DB_CONFIG)


# ── Análisis ──────────────────────────────────────────────────────────


def persistir_decision(caso_id: str, resultado: dict[str, Any]) -> None:
    """Persiste la decisión final del pipeline en la tabla ``resolution_case``.

    Consolida todos los resultados por caso: decisión, resultado de reglas y
    del LLM por separado (``decision_regla``/``decision_llm``), checklist por
    regla (JSONB), justificaciones (``justificacion_regla`` del pipeline /
    ``justificacion_llm`` del LLM) y señales separadas (``senales_regla`` /
    ``senales_llm``).

    Args:
        caso_id: Caso analizado.
        resultado: Estado final del grafo (final_decision, decision_regla, ...).
    """
    decision_regla = resultado.get("decision_regla")
    llm_resultado = resultado.get("llm_resultado")
    # ESCALAR forzado por reglas: la decisión es de las reglas aunque el LLM
    # haya generado análisis enriquecido (justificación/señales).
    fuente = "reglas" if decision_regla == "ESCALAR" else ("llm" if llm_resultado else "reglas")
    features_version = resultado.get("features_version", "v1")

    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO resolution_case
                       (caso_id, features_version, fuente, decision,
                        decision_regla, reglas_checklist,
                        decision_llm, justificacion_llm, justificacion_regla,
                        senales_llm, senales_regla, llm_resultado)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (caso_id) DO UPDATE SET
                        features_version   = EXCLUDED.features_version,
                        fuente             = EXCLUDED.fuente,
                        decision           = EXCLUDED.decision,
                        decision_regla     = EXCLUDED.decision_regla,
                        reglas_checklist   = EXCLUDED.reglas_checklist,
                        decision_llm       = EXCLUDED.decision_llm,
                        justificacion_llm  = EXCLUDED.justificacion_llm,
                        justificacion_regla = EXCLUDED.justificacion_regla,
                        senales_llm        = EXCLUDED.senales_llm,
                        senales_regla      = EXCLUDED.senales_regla,
                        llm_resultado      = EXCLUDED.llm_resultado,
                        updated_at         = NOW()""",
                (
                    caso_id,
                    features_version,
                    fuente,
                    resultado["final_decision"],
                    resultado.get("decision_regla", "AMBIGUO"),
                    jsonb(resultado.get("reglas_checklist") or []),
                    resultado.get("decision_llm"),
                    resultado.get("justificacion_llm"),
                    resultado.get("justificacion_regla") or None,
                    " | ".join(resultado.get("senales_llm") or []),
                    " | ".join(resultado.get("senales_regla") or []),
                    jsonb(llm_resultado),
                ),
            )
        conn.commit()
    finally:
        conn.close()


async def analizar_caso(case_id: str) -> dict[str, Any]:
    """Ejecuta el pipeline completo sobre un caso y persiste los resultados.

    Persiste la decisión consolidada en ``resolution_case``: decisión,
    resultado de reglas, checklist por regla (JSONB) y resultado del LLM.
    El checklist viaja en el estado (``reglas_checklist``); aquí solo se persiste.

    Args:
        case_id: Identificador del caso en la tabla ``cases``.

    Returns:
        Estado final del grafo.

    Raises:
        ValueError: Si el caso no existe.
        RuntimeError: Si el grafo no está inicializado.
    """
    graph = get_graph()
    if graph is None:
        raise RuntimeError("Grafo no inicializado")

    resultado = await graph.ainvoke({"case_id": case_id})
    # La persistencia es una escritura corta (<ms); se aísla para no bloquear
    # el event loop durante la espera de red del LLM.
    await asyncio.to_thread(persistir_decision, case_id, resultado)
    return resultado


# ── Jobs batch (en memoria, un proceso) ───────────────────────────────

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def _ejecutar_batch(job_id: str, case_ids: list[str]) -> None:
    """Worker del batch: analiza casos actualizando el job.

    Corre en un hilo background; crea un event loop propio con ``asyncio.run``
    porque el pipeline (grafo LangGraph) es asíncrono.
    """
    asyncio.run(_ejecutar_batch_async(job_id, case_ids))


async def _ejecutar_batch_async(job_id: str, case_ids: list[str]) -> None:
    """Analiza los casos del job de forma secuencial con el grafo async."""
    for case_id in case_ids:
        try:
            resultado = await analizar_caso(case_id)
            with _jobs_lock:
                job = _jobs[job_id]
                job["procesados"] += 1
                dec = resultado["final_decision"]
                job["decisiones"][dec] = job["decisiones"].get(dec, 0) + 1
        except Exception as e:
            logger.error("Batch %s: error en %s: %s", job_id, case_id, e)
            with _jobs_lock:
                _jobs[job_id]["errores"] += 1

    with _jobs_lock:
        _jobs[job_id]["status"] = "done"


def lanzar_batch(filtros: dict[str, Any]) -> tuple[str, int]:
    """Lanza un batch en background sobre los casos que cumplan los filtros.

    Args:
        filtros: ``es_sintetico`` (bool|None), ``solo_pendientes`` (bool),
            ``limite`` (int|None).

    Returns:
        Tupla (job_id, total_casos).
    """
    where, params = [], []
    if filtros.get("es_sintetico") is not None:
        where.append("es_sintetico = %s")
        params.append(filtros["es_sintetico"])
    if filtros.get("solo_pendientes"):
        where.append(
            "NOT EXISTS (SELECT 1 FROM resolution_case a WHERE a.caso_id = c.caso_id)"
        )

    sql = "SELECT c.caso_id FROM cases c"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY c.caso_id"
    if filtros.get("limite"):
        sql += " LIMIT %s"
        params.append(filtros["limite"])

    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            case_ids = [r["caso_id"] for r in cur.fetchall()]
    finally:
        conn.close()

    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "total": len(case_ids),
            "procesados": 0,
            "errores": 0,
            "decisiones": {},
        }

    hilo = threading.Thread(target=_ejecutar_batch, args=(job_id, case_ids), daemon=True)
    hilo.start()
    return job_id, len(case_ids)


def estado_job(job_id: str) -> dict[str, Any] | None:
    """Devuelve el estado de un job (None si no existe)."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None
