"""Seed de la tabla `casos` con los 150 casos originales del dataset.

Lee ``data/Dataset_caso_3.xlsx`` (pestaña ``Caso3_Compensaciones``) e inserta
los registros en PostgreSQL. Es idempotente: borra los casos originales
previos (``es_sintetico = FALSE``) antes de insertar.

Uso:
    python3 infra/db/seeds/seed_cases.py
"""

from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

EXCEL_PATH = Path(__file__).resolve().parents[3] / "data" / "Dataset_caso_3.xlsx"
SHEET_NAME = "Caso3_Compensaciones"

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "rappi_cases",
    "user": "rappi",
    "password": "rappi_pass",
}

COLUMNAS = [
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
    "recomendacion_agente",
]


def cargar_dataset() -> pd.DataFrame:
    """Carga el Excel del Caso 3 con el header en la fila correcta.

    Returns:
        DataFrame con los 150 casos originales.

    Raises:
        FileNotFoundError: Si el Excel no existe en ``data/``.
    """
    if not EXCEL_PATH.exists():
        raise FileNotFoundError(f"No se encontró el dataset: {EXCEL_PATH}")
    df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME, header=1)
    return df


def seed() -> int:
    """Inserta los casos originales en la tabla ``casos``.

    Returns:
        Cantidad de casos insertados.
    """
    df = cargar_dataset()

    faltantes = [c for c in COLUMNAS if c not in df.columns]
    if faltantes:
        raise ValueError(f"Columnas faltantes en el Excel: {faltantes}")

    df = df[COLUMNAS].copy()
    df["recomendacion_agente"] = df["recomendacion_agente"].where(
        df["recomendacion_agente"].notna(), None
    )

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            # Idempotente: borra solo los originales, respeta sintéticos
            cur.execute("DELETE FROM casos WHERE es_sintetico = FALSE;")
            valores = [tuple(fila) for fila in df.itertuples(index=False)]
            execute_values(
                cur,
                f"INSERT INTO casos ({', '.join(COLUMNAS)}) VALUES %s",
                valores,
            )
        conn.commit()
    finally:
        conn.close()

    return len(df)


if __name__ == "__main__":
    insertados = seed()
    print(f"[seed] Casos originales insertados: {insertados}")
