"""Ejecuta el pipeline por chunks para evitar timeouts."""

import asyncio
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, "/Users/fabro/Developer/Challenge/Rappi/case3_project")

import psycopg2

from src.pipeline.graph import build_graph

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "rappi_cases",
    "user": "rappi",
    "password": "rappi_pass",
}

CHUNK_SIZE = 30


def obtener_casos_pendientes() -> list[str]:
    """Obtiene caso_ids que aún no tienen análisis en analisis_casos."""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT c.caso_id FROM casos c
                   LEFT JOIN analisis_casos a ON a.caso_id = c.caso_id
                   WHERE a.id IS NULL
                   ORDER BY c.caso_id"""
            )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def actualizar_caso(caso_id: str, resultado: dict) -> None:
    """Persiste la decisión en la DB (tabla analisis_casos)."""
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


def main() -> None:
    """Procesa casos pendientes en chunks."""
    pendientes = obtener_casos_pendientes()
    total = len(pendientes)

    if total == 0:
        print("No hay casos pendientes.")
        return

    print(f"Casos pendientes: {total}")
    graph = build_graph()

    procesados = 0
    t0 = time.time()

    async def _procesar_pendientes() -> int:
        procesados = 0
        for caso_id in pendientes:
            try:
                resultado = await graph.ainvoke({"case_id": caso_id})
                await asyncio.to_thread(actualizar_caso, caso_id, resultado)
                procesados += 1

                if procesados % 10 == 0:
                    elapsed = time.time() - t0
                    print(f"  [{procesados}/{total}] {caso_id}: {resultado['final_decision']} ({elapsed:.0f}s)")
            except Exception as e:
                print(f"  [ERROR] {caso_id}: {e}")
        return procesados

    procesados = asyncio.run(_procesar_pendientes())
    print(f"\nCompletado: {procesados}/{total} en {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
