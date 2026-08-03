"""Repositorio del proceso batch durable en PostgreSQL.

Centraliza todo el SQL del batch: cabecera ``batch_runs``, items
``batch_run_items`` y la persistencia consolidada de resultados
(``persistir_resolucion``). Reemplaza la duplicación de ``INSERT ...
ON CONFLICT`` que existía en ``api/services.py`` y en los antiguos scripts
batch (eliminados; el entrypoint actual es ``scripts/run_batch.py``).

La conexión se abre y cierra por operación (worker y API son efímeros).
"""

import os
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from src.utils.jsonb import jsonb

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "dbname": os.environ.get("DB_NAME", "rappi_cases"),
    "user": os.environ.get("DB_USER", "rappi"),
    "password": os.environ.get("DB_PASSWORD", "rappi_pass"),
}

ESTADOS_ITEM = ("queued", "running", "done", "failed")

_INSERT_RESOLUCION = """
    INSERT INTO resolution_case
        (caso_id, features_version, fuente, decision,
         decision_regla, reglas_checklist,
         decision_llm, justificacion_llm, justificacion_regla,
         senales_llm, senales_regla, llm_resultado, batch_run_id, fallback)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        batch_run_id       = EXCLUDED.batch_run_id,
        fallback           = EXCLUDED.fallback,
        updated_at         = NOW()
"""


def _conectar() -> psycopg2.extensions.connection:
    return psycopg2.connect(cursor_factory=RealDictCursor, **DB_CONFIG)


# ── Persistencia de resultados (gap 1: fuente única) ───────────────────


def persistir_resolucion(caso_id: str, resultado: dict[str, Any], batch_run_id: int | None = None) -> None:
    """Persiste la decisión final del pipeline en ``resolution_case``.

    Fuente única del ``INSERT ... ON CONFLICT`` que antes vivía duplicado en
    tres sitios. Consolida decisión, resultado de reglas/LLM por separado,
    checklist (JSONB) y justificaciones/señales separadas.

    Args:
        caso_id: Caso analizado.
        resultado: Estado final del grafo (final_decision, decision_regla, ...).
        batch_run_id: Lote que generó el análisis (auditoría). None si el
            análisis fue on-demand (endpoint ``/analyze``).
    """
    decision_regla = resultado.get("decision_regla")
    llm_resultado = resultado.get("llm_resultado")
    # ESCALAR forzado por reglas: la decisión es de las reglas aunque el LLM
    # haya generado análisis enriquecido (justificación/señales).
    fuente = "reglas" if decision_regla == "ESCALAR" else ("llm" if llm_resultado else "reglas")
    features_version = resultado.get("features_version", "v1")
    fallback = " | ".join(resultado.get("fallback_info") or []) or None

    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                _INSERT_RESOLUCION,
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
                    batch_run_id,
                    fallback,
                ),
            )
        conn.commit()
    finally:
        conn.close()


# ── Cabecera del run ────────────────────────────────────────────────────


def crear_run(run_id: str, tipo_filtro: str, parametros: dict, persistir: bool, case_ids: list[str]) -> int:
    """Crea un run (cabecera) + sus items.

    Args:
        run_id: Identificador legible (uuid) del run.
        tipo_filtro: todos|pendientes|sintetico|seleccion|aleatorio.
        parametros: Filtros originales del request (JSONB).
        persistir: True escribe en ``resolution_case``; False modo demo.
        case_ids: Casos a procesar.

    Returns:
        id numérico del run (FK de ``batch_run_items``).
    """
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO batch_runs (run_id, estado, tipo_filtro, parametros, persistir, total)
                   VALUES (%s, 'running', %s, %s, %s, %s)
                   RETURNING id""",
                (run_id, tipo_filtro, jsonb(parametros) if parametros else None, persistir, len(case_ids)),
            )
            run_pk = cur.fetchone()["id"]
            cur.executemany(
                """INSERT INTO batch_run_items (run_id, caso_id, estado)
                   VALUES (%s, %s, 'queued')""",
                [(run_pk, c) for c in case_ids],
            )
        conn.commit()
        return run_pk
    finally:
        conn.close()


def reclamar_item(run_pk: int, max_intentos: int) -> tuple[int, str] | None:
    """Reclama un item ``queued`` para procesarlo (*at-least-once*).

    Un ``UPDATE ... RETURNING`` transaccional marca el item como ``running``
    atómicamente: si dos workers corren a la vez (o el proceso reintenta),
    solo uno obtiene cada item → no se duplica trabajo.

    Args:
        run_pk: id del ``batch_runs``.
        max_intentos: si un item ya llegó a ``max_intentos`` intentos, no se
            vuelve a reclamar (se deja como ``failed``).

    Returns:
        Tupla ``(item_id, caso_id)`` a procesar, o None si no quedan.
    """
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE batch_run_items
                   SET estado = 'running'
                   WHERE id = (
                       SELECT id FROM batch_run_items
                       WHERE run_id = %s AND estado = 'queued' AND intentos < %s
                       ORDER BY id
                       FOR UPDATE SKIP LOCKED
                       LIMIT 1
                   )
                   RETURNING id, caso_id""",
                (run_pk, max_intentos),
            )
            row = cur.fetchone()
        conn.commit()
        return (row["id"], row["caso_id"]) if row else None
    finally:
        conn.close()


def marcar_item(item_id: int, estado: str, intentos: int = 0, error: str | None = None, fila_demo: dict | None = None) -> None:
    """Actualiza el estado/resultado de un item del run.

    Args:
        item_id: id del ``batch_run_items``.
        estado: done (éxito) o failed (agotados intentos).
        intentos: número de intentos (para un estado fallido).
        error: mensaje de error (si falló).
        fila_demo: en modo demo (persistir=FALSE), fila del Excel para
            descargar sin escribir en ``resolution_case``.
    """
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            if estado == "done":
                cur.execute(
                    """UPDATE batch_run_items
                       SET estado = 'done', procesado_en = NOW(),
                           fila_demo = COALESCE(%s, fila_demo)
                       WHERE id = %s""",
                    (jsonb(fila_demo) if fila_demo else None, item_id),
                )
            else:
                cur.execute(
                    "UPDATE batch_run_items SET estado = %s, intentos = %s, error = %s WHERE id = %s",
                    (estado, intentos, error, item_id),
                )
        conn.commit()
    finally:
        conn.close()


def incrementar_item_fallido(item_id: int, error: str, max_intentos: int) -> str:
    """Suma un intento al item; ``queued`` para reintentar o ``failed`` al límite.

    Returns:
        El nuevo estado del item ('queued' si queda intento, 'failed' si agotó).
    """
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE batch_run_items
                   SET intentos = intentos + 1,
                       error = %s,
                       estado = CASE WHEN intentos + 1 >= %s THEN 'failed' ELSE 'queued' END,
                       procesado_en = NOW()
                   WHERE id = %s
                   RETURNING estado""",
                (error, max_intentos, item_id),
            )
            row = cur.fetchone()
        conn.commit()
        return row["estado"] if row else "failed"
    finally:
        conn.close()


def agregar_estado_run(run_pk: int, decision: str, error: bool = False) -> None:
    """Acumula una decisión (o un error) en la cabecera del run."""
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(decisiones, '{}') AS d FROM batch_runs WHERE id = %s FOR UPDATE",
                (run_pk,),
            )
            row = cur.fetchone()
            if row is None:
                return
            decisiones = row["d"]
            if error:
                cur.execute("UPDATE batch_runs SET errores = errores + 1 WHERE id = %s", (run_pk,))
            else:
                decisiones[decision] = decisiones.get(decision, 0) + 1
                cur.execute(
                    """UPDATE batch_runs
                       SET decisiones = %s, procesados = procesados + 1
                       WHERE id = %s""",
                    (jsonb(decisiones), run_pk),
                )
        conn.commit()
    finally:
        conn.close()


def completar_run(run_pk: int, estado: str = "done") -> None:
    """Marca un run como terminado con timestamp de fin."""
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE batch_runs SET estado = %s, finalizado_en = NOW() WHERE id = %s",
                (estado, run_pk),
            )
        conn.commit()
    finally:
        conn.close()


def leer_total_run(run_pk: int) -> int:
    """Devuelve el total de casos del run (para acotar el job timeout)."""
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT total FROM batch_runs WHERE id = %s", (run_pk,))
            row = cur.fetchone()
            return int(row["total"]) if row else 0
    finally:
        conn.close()


# ── Consulta de estado y recuperación ──────────────────────────────────


def estado_run(run_id: str) -> dict[str, Any] | None:
    """Devuelve el estado del run (None si no existe)."""
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT run_id AS job_id, estado AS status, total, procesados,
                          errores, COALESCE(decisiones, '{}') AS decisiones
                   FROM batch_runs WHERE run_id = %s""",
                (run_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def filas_run(run_id: str) -> list[dict[str, Any]]:
    """Devuelve las filas demo (modo ``persistir=False``) de un run.

    Solo contiene filas cuando el batch se lanzó sin persistir
    (``fila_demo`` no NULL). Vacío si el run no aplica o no existe.
    """
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT f.fila_demo FROM batch_run_items f
                   JOIN batch_runs r ON r.id = f.run_id
                   WHERE r.run_id = %s AND f.fila_demo IS NOT NULL
                   ORDER BY f.id""",
                (run_id,),
            )
            return [dict(r["fila_demo"]) for r in cur.fetchall()]
    finally:
        conn.close()


def recuperar_runs_huerfanos() -> int:
    """Revierte a ``error`` los runs ``running`` y los items a ``queued``.

    Se llama al arrancar la API: si el proceso murió con un job en vuelo,
    este run ya no se procesará, así que marca sus items ``running``/``queued``
    y lo deja constatado como ``error``. Los items ``done`` permanecen
    (la persistencia ya se hizo).
    """
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM batch_runs WHERE estado = 'running'")
            ids = [r["id"] for r in cur.fetchall()]
            for pk in ids:
                cur.execute("UPDATE batch_run_items SET estado = 'queued' WHERE run_id = %s AND estado = 'running'", (pk,))
            if ids:
                cur.execute(
                    "UPDATE batch_runs SET estado = 'error', finalizado_en = NOW() WHERE id = ANY(%s)",
                    (ids,),
                )
        conn.commit()
        return len(ids)
    finally:
        conn.close()