"""Servicios de la API: análisis de casos, persistencia, jobs batch y export."""

import asyncio
import io
import logging
import threading
import uuid
from typing import Any

import pandas as pd
import psycopg2
import psycopg2.extras

from src.batch import repository as batch_repo
from src.batch.rows import resumen_llm
from src.batch.worker import procesar_run_async
from src.utils.db import DB_CONFIG

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
    """Persiste la decisión final del pipeline en ``resolution_case`` (análisis on-demand).

    Delega en la fuente única ``src.batch.repository.persistir_resolucion``
    (con ``batch_run_id`` nulo: no pertenece a un lote). Consolida todas las
    variables de decisión con su origen separado (reglas/LLM).

    Args:
        caso_id: Caso analizado.
        resultado: Estado final del grafo (final_decision, decision_regla, ...).
    """
    batch_repo.persistir_resolucion(caso_id, resultado)


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
    resultado = await analizar_caso_memoria(case_id)
    # La persistencia es una escritura corta (<ms); se aísla para no bloquear
    # el event loop durante la espera de red del LLM.
    await asyncio.to_thread(persistir_decision, case_id, resultado)
    return resultado


async def analizar_caso_memoria(case_id: str) -> dict[str, Any]:
    """Ejecuta el pipeline completo sobre un caso SIN persistir nada.

    Corre el grafo completo (reglas + LLM cuando aplica) pero no toca
    ``resolution_case``. Pensado para demos y simulación: el resultado
    queda solo en memoria.

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
    return await graph.ainvoke({"case_id": case_id})


# ── Jobs batch (durable en PostgreSQL) ────────────────────────────────

# Tipos de filtro soportados por el request (para ``batch_runs.tipo_filtro``).
_TIPO_FILTRO = {
    "case_ids_manual": "seleccion",
    "aleatorio": "aleatorio",
    "es_sintetico": "sintetico",
    "solo_pendientes": "pendientes",
}


def _resolver_casos(filtros: dict[str, Any]) -> tuple[list[str], str]:
    """Resuelve los ``case_id`` a procesar según los filtros.

    Returns:
        Tupla (case_ids, tipo_filtro).
    """
    if filtros.get("case_ids"):
        return list(filtros["case_ids"]), _TIPO_FILTRO["case_ids_manual"]

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
    sql += " ORDER BY RANDOM()" if filtros.get("aleatorio") else " ORDER BY c.caso_id"
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

    if filtros.get("aleatorio"):
        tipo = "aleatorio"
    elif filtros.get("es_sintetico") is not None:
        tipo = "sintetico"
    else:
        tipo = "pendientes" if filtros.get("solo_pendientes") else "todos"
    return case_ids, tipo


def _worker_thread(run_pk: int, persistir: bool) -> None:
    """Body del thread: corre el worker con el grafo del proceso (event loop propio)."""
    asyncio.run(procesar_run_async(get_graph(), run_pk, persistir))


def lanzar_batch(filtros: dict[str, Any]) -> tuple[str, int]:
    """Lanza un batch durable en background sobre los casos que cumplan los filtros.

    El estado del job vive en ``batch_runs``/``batch_run_items`` (PostgreSQL),
    no en memoria: sobrevive a reinicios (los runs huérfanos se recuperan en el
    arranque), permite retry por caso y auditoría de qué lote generó cada caso.

    Args:
        filtros: ``case_ids`` (list[str]|None) selección manual,
            ``aleatorio`` (bool) muestreo aleatorio con ``limite``,
            ``persistir`` (bool) True escribe en ``resolution_case``
            (default; ``False`` = demo en memoria), ``es_sintetico`` (bool|None),
            ``solo_pendientes`` (bool), ``limite`` (int|None).

    Returns:
        Tupla (job_id, total_casos).
    """
    persistir = filtros.get("persistir", True)
    case_ids, tipo_filtro = _resolver_casos(filtros)

    run_id = uuid.uuid4().hex[:12]
    run_pk = batch_repo.crear_run(run_id, tipo_filtro, filtros, persistir, case_ids)

    hilo = threading.Thread(
        target=_worker_thread, args=(run_pk, persistir), daemon=True
    )
    hilo.start()
    return run_id, len(case_ids)


def estado_job(job_id: str) -> dict[str, Any] | None:
    """Devuelve el estado de un run desde PostgreSQL (None si no existe)."""
    return batch_repo.estado_run(job_id)


def filas_job(job_id: str) -> list[dict[str, Any]]:
    """Devuelve las filas del job demo (modo ``persistir=False``) desde la DB."""
    return batch_repo.filas_run(job_id)


# ── Export (Excel de casos analizados) ────────────────────────────────

# Columnas del entregable; el orden define el Excel (DB y modo memoria).
EXPORT_COLUMNS = [
    "caso_id",
    "usuario_id",
    "antiguedad_usuario_dias",
    "ciudad",
    "vertical",
    "restaurante",
    "valor_orden_mxn",
    "compensacion_solicitada_mxn",
    "num_compensaciones_90d",
    "monto_compensado_90d_mxn",
    "entrega_confirmada_gps",
    "tiempo_entrega_real_min",
    "flags_fraude_previos",
    "motivo_reclamo",
    "descripcion_reclamo",
    "comp_ratio",
    "freq_densidad",
    "score_riesgo_previo",
    "fuente",
    "recomendacion",
    "decision_regla",
    "decision_llm",
    "justificacion_llm",
    "justificacion_regla",
    "senales_llm",
    "senales_regla",
    "resumen_llm",
    "fallback",
]

QUERY_EXPORT = """
    SELECT c.caso_id,
           c.usuario_id,
           c.antiguedad_usuario_dias,
           c.ciudad,
           c.vertical,
           c.restaurante,
           c.valor_orden_mxn,
           c.compensacion_solicitada_mxn,
           c.num_compensaciones_90d,
           c.monto_compensado_90d_mxn,
           c.entrega_confirmada_gps,
           c.tiempo_entrega_real_min,
           c.flags_fraude_previos,
           c.motivo_reclamo,
           c.descripcion_reclamo,
           f.comp_ratio,
           f.freq_densidad,
           f.score_riesgo_previo,
           a.fuente,
           a.decision            AS recomendacion,
           a.decision_regla,
           a.decision_llm,
           a.justificacion_llm,
           a.justificacion_regla,
           a.senales_llm,
           a.senales_regla,
           a.llm_resultado,
           a.fallback
    FROM cases c
    LEFT JOIN features f ON f.caso_id = c.caso_id
    LEFT JOIN resolution_case a ON a.caso_id = c.caso_id
    {where}
    ORDER BY c.caso_id
"""


def _resumen_llm(llm_resultado: Any) -> str:
    """Extrae el resumen legible del JSONB del LLM (o '' si no aplica)."""
    return resumen_llm(llm_resultado)  # fuente única en src/batch/rows.py


def generar_excel_bytes(es_sintetico: bool = False) -> bytes:
    """Genera el Excel de casos analizados como bytes (sin tocar disco).

    Args:
        es_sintetico: ``False`` = 150 casos originales (default);
            ``True`` = 250 casos (originales + sintéticos).

    Returns:
        Contenido del archivo xlsx en memoria.
    """
    if es_sintetico:
        sql = QUERY_EXPORT.format(where="")
    else:
        sql = QUERY_EXPORT.format(where="WHERE c.es_sintetico = FALSE")

    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            filas = cur.fetchall()
    finally:
        conn.close()

    df = pd.DataFrame(filas)

    df["resumen_llm"] = df["llm_resultado"].map(_resumen_llm)
    df = df.drop(columns=["llm_resultado"])
    df = df[EXPORT_COLUMNS]

    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, sheet_name="Caso3_Compensaciones")
    return buffer.getvalue()


def excel_filas_bytes(filas: list[dict[str, Any]]) -> bytes:
    """Genera un Excel en memoria a partir de filas planas (modo demo)."""
    df = pd.DataFrame(filas, columns=EXPORT_COLUMNS)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, sheet_name="Caso3_Compensaciones")
    return buffer.getvalue()
