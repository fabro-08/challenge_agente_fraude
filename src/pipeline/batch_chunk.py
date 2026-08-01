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
from src.utils.jsonb import jsonb

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "rappi_cases",
    "user": "rappi",
    "password": "rappi_pass",
}

CHUNK_SIZE = 30


def obtener_casos_pendientes() -> list[str]:
    """Obtiene caso_ids que aún no tienen análisis en resolution_case."""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT c.caso_id FROM cases c
                   LEFT JOIN resolution_case a ON a.caso_id = c.caso_id
                   WHERE a.caso_id IS NULL
                   ORDER BY c.caso_id"""
            )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def actualizar_caso(caso_id: str, resultado: dict) -> None:
    """Persiste la decisión en la DB (tabla resolution_case)."""
    decision_regla = resultado.get("decision_regla")
    llm_res = resultado.get("llm_resultado")
    # ESCALAR forzado por reglas: la decisión es de las reglas aunque el LLM
    # haya generado análisis enriquecido (justificación/señales).
    fuente = "reglas" if decision_regla == "ESCALAR" else ("llm" if llm_res else "reglas")
    features_version = resultado.get("features_version", "v1")

    conn = psycopg2.connect(**DB_CONFIG)
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
                    jsonb(llm_res),
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
