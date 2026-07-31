"""Ejecuta el pipeline LangGraph sobre todos los casos de la DB.

Procesa los 150 originales + 100 sintéticos y persiste la decisión final
en PostgreSQL (tabla analisis_casos: decision, justificacion, senales_usadas,
llm_resultado).

El grafo es asíncrono (nodo LLM ``async``); el batch corre dentro de un event
loop propio vía ``asyncio.run``. Para una corrida de backfill, la ejecución
secuencial es suficiente; la concurrencia on-demand vive en la API (FastAPI +
``asyncio.Semaphore`` en el nodo LLM).
"""

import asyncio
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2

from src.pipeline.graph import build_graph

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "rappi_cases"),
    "user": os.getenv("DB_USER", "rappi"),
    "password": os.getenv("DB_PASSWORD", "rappi_pass"),
}


def obtener_casos() -> list[str]:
    """Obtiene todos los caso_id de la DB.

    Returns:
        Lista de caso_id.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT caso_id FROM casos ORDER BY caso_id")
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def actualizar_caso(caso_id: str, resultado: dict) -> None:
    """Persiste la decisión del pipeline en la tabla analisis_casos.

    Args:
        caso_id: ID del caso a actualizar.
        resultado: Dict con final_decision, justification, signals.
    """
    import psycopg2.extras
    fuente = "llm" if resultado.get("llm_resultado") else "reglas"
    llm_res = resultado.get("llm_resultado") if fuente == "llm" else None

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO analisis_casos
                       (caso_id, fuente, decision, justificacion, senales_usadas,
                        llm_resultado)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (caso_id) DO UPDATE SET
                        fuente          = EXCLUDED.fuente,
                        decision        = EXCLUDED.decision,
                        justificacion   = EXCLUDED.justificacion,
                        senales_usadas  = EXCLUDED.senales_usadas,
                        llm_resultado   = EXCLUDED.llm_resultado,
                        updated_at      = NOW()""",
                (
                    caso_id,
                    fuente,
                    resultado["final_decision"],
                    resultado["justification"],
                    " | ".join(resultado["signals"]),
                    psycopg2.extras.Json(llm_res) if llm_res else None,
                ),
            )
        conn.commit()
    finally:
        conn.close()


async def _procesar_casos(graph, casos: list[str], total: int) -> dict:
    """Procesa los casos secuencialmente sobre el event loop del batch."""
    stats = {"APROBAR": 0, "RECHAZAR": 0, "ESCALAR": 0}
    t0 = time.time()

    for i, caso_id in enumerate(casos, 1):
        try:
            resultado = await graph.ainvoke({"case_id": caso_id})
            await asyncio.to_thread(actualizar_caso, caso_id, resultado)
            stats[resultado["final_decision"]] += 1

            if i % 10 == 0 or i == total:
                elapsed = time.time() - t0
                eta = (elapsed / i) * (total - i) if i > 0 else 0
                print(
                    f"  [{i}/{total}] {caso_id}: {resultado['final_decision']} "
                    f"(ETA: {eta:.0f}s)"
                )
        except Exception as e:
            print(f"  [ERROR] {caso_id}: {e}")
            stats["ESCALAR"] += 1
    return stats


def main() -> None:
    """Ejecuta el pipeline sobre todos los casos."""
    casos = obtener_casos()
    graph = build_graph()

    total = len(casos)
    print(f"Procesando {total} casos...")
    t0 = time.time()
    stats = asyncio.run(_procesar_casos(graph, casos, total))
    print(f"\nCompletado en {time.time() - t0:.0f}s")
    print(f"Resultados: {stats}")


if __name__ == "__main__":
    main()
