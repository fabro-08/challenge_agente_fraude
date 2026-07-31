#!/usr/bin/env python3
"""Exporta los 150 casos originales analizados a un Excel entregable.

Genera ``data/150casos_analizados.xlsx`` con los campos que el agente CS
necesita para actuar: decisión, justificación, señales usadas y el resumen
del LLM (cuando aplica) para los casos del dataset original.

Uso:
    python scripts/export_casos_analizados.py [--output data/150casos_analizados.xlsx]
"""

import argparse
import json
import os

import pandas as pd
import psycopg2

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "dbname": os.environ.get("DB_NAME", "rappi_cases"),
    "user": os.environ.get("DB_USER", "rappi"),
    "password": os.environ.get("DB_PASSWORD", "rappi_pass"),
}

QUERY = """
    SELECT c.caso_id,
           c.usuario_id,
           c.antiguedad_usuario_dias,
           c.ciudad,
           c.vertical,
           c.restaurante,
           c.valor_orden_mxn,
           c.compensacion_solicitada_mxn,
           c.num_compensaciones_90d,
           c.monto_compensado_90d_mxn,
           c.entrega_confirmada_gps,
           c.tiempo_entrega_real_min,
           c.flags_fraude_previos,
           c.motivo_reclamo,
           c.descripcion_reclamo,
           c.comp_ratio,
           c.freq_densidad,
           c.score_riesgo_previo,
           a.fuente,
           a.decision            AS recomendacion,
           a.justificacion,
           a.senales_usadas,
           a.llm_resultado
    FROM casos c
    LEFT JOIN analisis_casos a ON a.caso_id = c.caso_id
    WHERE c.es_sintetico = FALSE
    ORDER BY c.caso_id
"""


def _resumen_llm(llm_resultado) -> str:
    """Extrae el resumen legible del JSONB del LLM (o '' si no aplica)."""
    if not llm_resultado:
        return ""
    try:
        data = llm_resultado if isinstance(llm_resultado, dict) else json.loads(llm_resultado)
    except (TypeError, json.JSONDecodeError):
        return str(llm_resultado)
    veredicto = data.get("veredicto", "")
    resumen = data.get("resumen", "")
    partes = [p for p in (veredicto, resumen) if p]
    return " | ".join(partes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/150casos_analizados.xlsx")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        df = pd.read_sql_query(QUERY, conn)
    finally:
        conn.close()

    df["resumen_llm"] = df["llm_resultado"].map(_resumen_llm)
    df = df.drop(columns=["llm_resultado"])

    output = args.output
    os.makedirs(os.path.dirname(output), exist_ok=True)
    df.to_excel(output, index=False, sheet_name="Caso3_Compensaciones")

    print(f"Exportadas {len(df)} filas → {output}")
    print(df["recomendacion"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
