"""Nodo load_case: carga los datos crudos del caso desde PostgreSQL.

Los datos crudos vienen de la tabla ``cases`` (capa 1). Las features se cargan
o calculan en ``compute_features``.
"""

import os

import psycopg2

from src.pipeline.state import CaseState


def load_case(state: CaseState) -> CaseState:
    """Carga los datos crudos del caso desde PostgreSQL.

    Args:
        state: Estado actual con ``case_id``.

    Returns:
        Estado actualizado con ``raw_data`` y ``es_sintetico``.

    Raises:
        ValueError: Si el caso no existe en la base de datos.
    """
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "rappi_cases"),
        user=os.getenv("DB_USER", "rappi"),
        password=os.getenv("DB_PASSWORD", "rappi_pass"),
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT caso_id, usuario_id, antiguedad_usuario_dias, ciudad,
                          vertical, restaurante, valor_orden_mxn,
                          compensacion_solicitada_mxn, num_compensaciones_90d,
                          monto_compensado_90d_mxn, entrega_confirmada_gps,
                          tiempo_entrega_real_min, flags_fraude_previos,
                          motivo_reclamo, descripcion_reclamo,
                          recomendacion_agente, es_sintetico
                   FROM cases WHERE caso_id = %s""",
                (state["case_id"],),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Caso {state['case_id']} no encontrado")
            cols = [desc[0] for desc in cur.description]
            raw = dict(zip(cols, row))
    finally:
        conn.close()

    state["raw_data"] = raw
    state["es_sintetico"] = bool(raw.get("es_sintetico", False))
    return state
