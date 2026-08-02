"""Backfill de ``justificacion_regla`` al formato multilínea con explicación.

1. Sincroniza ``explicacion`` (texto preseteado por regla) en las configs de la
   versión actual de ``reglas_versiones``, tomándola de
   ``src/rules/thresholds.yaml`` (misma fuente que el seed de bootstrap).
2. Recalcula ``resolution_case.justificacion_regla`` para los casos resueltos
   por reglas (``justificacion_regla <> ''``) reutilizando el MISMO código del
   pipeline (``evaluar_reglas_generico`` + ``final_decision._justificacion_reglas``),
   garantizando consistencia de formato sin drift.

Determinista: no usa LLM. Los casos AMBIGUO/LLM (``justificacion_regla`` vacía)
no se tocan. Idempotente: solo actualiza filas cuyo texto cambia.

Uso::

    python scripts/backfill_justificacion_regla.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2

from src.pipeline.nodes.apply_rules import evaluar_reglas_generico
from src.pipeline.nodes.final_decision import _justificacion_reglas
from src.rules import repository, seed_reglas
from src.utils.jsonb import jsonb


def _sincronizar_explicaciones(cur: psycopg2.extensions.cursor) -> int:
    """Agrega ``explicacion`` a la config de la versión actual de cada regla."""
    actualizados = 0
    for regla_id, _nombre, _tipo, _prioridad, config in seed_reglas.construir_seed():
        if "explicacion" not in config:
            continue
        cur.execute(
            """
            UPDATE reglas_versiones
            SET config = config || %s
            WHERE regla_id = %s
              AND version = (SELECT version_actual FROM configuracion_reglas
                             WHERE regla_id = %s)
              AND config->>'explicacion' IS DISTINCT FROM %s
            """,
            (jsonb({"explicacion": config["explicacion"]}), regla_id, regla_id, config["explicacion"]),
        )
        actualizados += cur.rowcount
    return actualizados


def _features_de_caso(cur: psycopg2.extensions.cursor, caso_id: str) -> dict | None:
    """Features del caso como dict (columnas de ``cases`` + ``features``)."""
    cur.execute(
        """
        SELECT c.*, f.*
        FROM cases c
        LEFT JOIN features f ON f.caso_id = c.caso_id
        WHERE c.caso_id = %s
        """,
        (caso_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip((d.name for d in cur.description), row))


def main() -> None:
    conn = psycopg2.connect(**repository.DB_CONFIG)
    try:
        with conn.cursor() as cur:
            n_conf = _sincronizar_explicaciones(cur)
            print(f"[OK] configs con explicacion sincronizadas: {n_conf}")
            conn.commit()  # visible para las conexiones del motor (cargar_reglas_activas)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT caso_id, decision, justificacion_regla "
                "FROM resolution_case WHERE justificacion_regla <> '' ORDER BY caso_id"
            )
            casos = cur.fetchall()
            print(f"[INFO] casos resueltos por reglas a revisar: {len(casos)}")

        actualizados = 0
        errores = 0
        with conn.cursor() as cur:
            for caso_id, decision, previo in casos:
                features = _features_de_caso(cur, caso_id)
                if not features:
                    print(f"[WARN] sin features para {caso_id}")
                    errores += 1
                    continue
                rule_details, _motor = evaluar_reglas_generico(features)
                nuevo = _justificacion_reglas(rule_details, decision)
                if nuevo == previo:
                    continue
                cur.execute(
                    "UPDATE resolution_case SET justificacion_regla = %s, updated_at = NOW() "
                    "WHERE caso_id = %s",
                    (nuevo, caso_id),
                )
                actualizados += 1
        conn.commit()
        print(f"[OK] justificacion_regla actualizados: {actualizados} · errores: {errores}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
