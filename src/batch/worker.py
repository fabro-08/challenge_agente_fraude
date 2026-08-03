"""Worker del proceso batch durable (retry + recuperación).

Procesa los items de un ``batch_runs`` leyendo de PostgreSQL (no de memoria):
cada corrutina reclama un item ``queued`` con un ``UPDATE ... RETURNING``
transaccional (``FOR UPDATE SKIP LOCKED``) → garantiza semántica
*at-least-once* sin duplicar trabajo. Cada caso se corre por el grafo
LangGraph; si falla, se reintenta hasta ``MAX_INTENTOS`` antes de marcarlo
``failed``.

La concurrencia está acotada por ``batch_concurrencia`` (config LLM); el LLM,
además, tiene su propio semáforo de rate-limit por event loop
(``src/pipeline/nodes/llm_classify.py``).
"""

import asyncio
import logging

from src.batch.repository import (
    agregar_estado_run,
    completar_run,
    incrementar_item_fallido,
    leer_total_run,
    marcar_item,
    persistir_resolucion,
    reclamar_item,
)
from src.batch.rows import fila_export_desde_estado
from src.config import get_llm_config

logger = logging.getLogger(__name__)

# 2 intentos por caso (primero + 1 reintento). Al superarlo → ``failed``.
MAX_INTENTOS = 2


def _presupuesto_job(total: int, concurrencia: int) -> float:
    """Tiempo máximo del job: escala con el volumen (sin cortar lotes grandes)."""
    cfg = get_llm_config()
    presupuesto = (total / max(1, concurrencia)) * cfg.caso_timeout_s + 60.0
    return min(presupuesto, cfg.jobs_max_timeout_s)


async def _procesar_item_worker(graph, run_pk: int, persistir: bool) -> None:
    """Bucle de un worker: reclama y procesa items hasta agotar cola."""
    while True:
        item = await asyncio.to_thread(reclamar_item, run_pk, MAX_INTENTOS)
        if item is None:
            return
        item_id, caso_id = item

        try:
            resultado = await asyncio.wait_for(
                graph.ainvoke({"case_id": caso_id}),
                timeout=get_llm_config().caso_timeout_s,
            )
        except Exception as e:
            logger.error("Batch run %s: fallo en %s: %s", run_pk, caso_id, e)
            estado = await asyncio.to_thread(
                incrementar_item_fallido, item_id, str(e), MAX_INTENTOS
            )
            if estado == "failed":
                await asyncio.to_thread(agregar_estado_run, run_pk, None, error=True)
            continue

        try:
            if persistir:
                await asyncio.to_thread(persistir_resolucion, caso_id, resultado, run_pk)
                await asyncio.to_thread(marcar_item, item_id, "done")
            else:
                fila = fila_export_desde_estado(resultado)
                await asyncio.to_thread(marcar_item, item_id, "done", fila_demo=fila)
        except Exception as e:
            logger.error("Batch run %s: persistencia fallida en %s: %s", run_pk, caso_id, e)
            estado = await asyncio.to_thread(
                incrementar_item_fallido, item_id, str(e), MAX_INTENTOS
            )
            if estado == "failed":
                await asyncio.to_thread(agregar_estado_run, run_pk, None, error=True)
            continue

        await asyncio.to_thread(agregar_estado_run, run_pk, resultado["final_decision"])


async def procesar_run_async(graph, run_pk: int, persistir: bool = True) -> None:
    """Procesa todos los items pendientes de un run con concurrencia acotada.

    Args:
        graph: Grafo LangGraph compilado (se reusa entre corridas).
        run_pk: id del ``batch_runs`` (items ya dados de alta).
        persistir: True escribe en ``resolution_case`` (con ``batch_run_id``);
            False corre en memoria y guarda la fila demo para descargar.
    """
    concurrencia = max(1, get_llm_config().batch_concurrencia)
    total = await asyncio.to_thread(leer_total_run, run_pk)
    timeout = _presupuesto_job(total, concurrencia)
    try:
        await asyncio.wait_for(
            asyncio.gather(
                *(
                    _procesar_item_worker(graph, run_pk, persistir)
                    for _ in range(concurrencia)
                )
            ),
            timeout=timeout,
        )
        estado = "done"
    except TimeoutError:
        logger.error("Batch run %s: excedido job timeout de %.0fs", run_pk, timeout)
        estado = "error"
    finally:
        await asyncio.to_thread(completar_run, run_pk, estado)


def procesar_run(run_pk: int, persistir: bool = True) -> None:
    """Wrapper síncrono (entrypoints CLI) que crea su propio event loop."""
    from src.pipeline.graph import build_graph

    graph = build_graph()
    asyncio.run(procesar_run_async(graph, run_pk, persistir))