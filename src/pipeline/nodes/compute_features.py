"""Nodo compute_features: carga/persiste features y las deja en el estado.

Flujo:
1. Si el caso ya tiene features persistidas en la tabla ``features`` → las usa
   (así no se re-calculan ni se sobreescriben).
2. Si no → las calcula de forma determinista desde ``raw_data`` y las persiste
   (upsert) para que queden disponibles sin reprocesar el caso.

``features.version`` se copia a ``state['features_version']``; el nodo de
persistencia lo audita en ``resolution_case.features_version``.
"""

import os

import psycopg2

from src.pipeline.features import calcular_features, cargar_features, persistir_features
from src.pipeline.state import CaseState

VERSION_FEATURES = "v1"


def _conectar() -> psycopg2.extensions.connection:
    """Conexión PostgreSQL con las variables de entorno por defecto."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "rappi_cases"),
        user=os.getenv("DB_USER", "rappi"),
        password=os.getenv("DB_PASSWORD", "rappi_pass"),
    )


def compute_features(state: CaseState) -> CaseState:
    """Calcula (o carga) las features del caso y las persiste si son nuevas.

    Args:
        state: Estado con ``case_id`` y ``raw_data``.

    Returns:
        Estado actualizado con ``features`` (raw + features) y
        ``features_version``.
    """
    raw = state["raw_data"]
    case_id = state["case_id"]

    conn = _conectar()
    try:
        existentes = cargar_features(conn, case_id)
        if existentes is not None:
            features = {k: v for k, v in existentes.items() if k != "version"}
            state["features_version"] = existentes.get("version", VERSION_FEATURES)
        else:
            features = calcular_features(raw)
            persistir_features(conn, case_id, features, VERSION_FEATURES)
            conn.commit()
            state["features_version"] = VERSION_FEATURES
    finally:
        conn.close()

    # El motor de reglas evalúa sobre raw + features combinados.
    state["features"] = {**raw, **features}
    return state
