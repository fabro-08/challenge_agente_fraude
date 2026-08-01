#!/usr/bin/env python3
"""Backfill de la tabla ``features`` desde datos crudos (migración 3 capas).

La migración ``10_migrate_3capas.sql`` ya copia las features existentes desde
la tabla legacy ``casos``. Este script es el respaldo: rellena cualquier hueco
(casos sin fila en ``features``) calculando las features de forma determinista
con ``src.pipeline.features.calcular_features``.

No modifica ``cases`` ni ``resolution_case``.

Uso:
    python scripts/backfill_features.py
"""

import os
import sys

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline.features import calcular_features, cargar_features, persistir_features

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "dbname": os.environ.get("DB_NAME", "rappi_cases"),
    "user": os.environ.get("DB_USER", "rappi"),
    "password": os.environ.get("DB_PASSWORD", "rappi_pass"),
}

VERSION_FEATURES = "v1"


def main() -> None:
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT caso_id FROM cases ORDER BY caso_id")
            casos = [r["caso_id"] for r in cur.fetchall()]

            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur_raw:
                pendientes = 0
                for caso_id in casos:
                    if cargar_features(conn, caso_id) is not None:
                        continue
                    cur_raw.execute(
                        """SELECT caso_id, usuario_id, antiguedad_usuario_dias,
                                  ciudad, vertical, restaurante, valor_orden_mxn,
                                  compensacion_solicitada_mxn,
                                  num_compensaciones_90d,
                                  monto_compensado_90d_mxn,
                                  entrega_confirmada_gps, tiempo_entrega_real_min,
                                  flags_fraude_previos, motivo_reclamo,
                                  descripcion_reclamo, recomendacion_agente
                           FROM cases WHERE caso_id = %s""",
                        (caso_id,),
                    )
                    raw = dict(cur_raw.fetchone())
                    features = calcular_features(raw)
                    persistir_features(conn, caso_id, features, VERSION_FEATURES)
                    pendientes += 1
    finally:
        conn.close()

    total = len(casos)
    print(f"[backfill_features] {total} casos revisados, {pendientes} features calculadas")


if __name__ == "__main__":
    main()
