"""Features derivadas del caso (capa 2 de 3).

Cálculo determinista de features a partir de datos crudos + acceso a la
tabla ``features``. El pipeline y el backfill comparten estas funciones para
que el feature engineering se pueda reprocesar sin tocar ``cases``.

La mayoría de features se derivan de reglas de negocio y percentiles de
referencia calculados sobre el dataset original (``data/casos_con_features.parquet``).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2.extras
from psycopg2.extensions import connection

PALABRAS_CRITICAS = re.compile(
    r"alergi|intoxic|polic[ií]a|sangre|insult|denunci|abogado|demanda|hospital|veneno",
    re.IGNORECASE,
)

# Columnas de features que viven en la tabla `features` (no en `cases`).
FEATURE_COLUMNS: tuple[str, ...] = (
    "comp_ratio",
    "comps_por_dia",
    "monto_promedio_comp",
    "gps_match_ok",
    "entrega_demorada",
    "burn_rate",
    "freq_densidad",
    "flag_inconsistencia_gps",
    "flag_mentira_gps_alta",
    "flag_retraso_critico",
    "flag_account_abuse",
    "score_riesgo_previo",
    "longitud_reclamo",
    "flag_palabras_criticas",
    "riesgo_ciudad",
    "riesgo_vertical",
    "gps_paradoja_score",
    "sospecha_nuevo_recurrente",
    "ratio_deviation",
    "score_texto",
)

_PARQUET_REF = Path(__file__).resolve().parents[2] / "data" / "casos_con_features.parquet"


@lru_cache(maxsize=1)
def _cargar_percentiles() -> dict[str, float]:
    """Carga los percentiles de referencia del dataset con features.

    Returns:
        Diccionario con p90_tiempo, p95_comp, p95_ncomps, p90_ncomps.
    """
    df = pd.read_parquet(_PARQUET_REF)
    return {
        "p90_tiempo": float(df["tiempo_entrega_real_min"].quantile(0.90)),
        "p95_comp": float(df["compensacion_solicitada_mxn"].quantile(0.95)),
        "p95_ncomps": float(df["num_compensaciones_90d"].quantile(0.95)),
        "p90_ncomps": float(df["num_compensaciones_90d"].quantile(0.90)),
    }


@lru_cache(maxsize=1)
def _df_referencia() -> pd.DataFrame:
    """DataFrame de referencia (tasas de ciudad/vertical y comp_ratio)."""
    return pd.read_parquet(_PARQUET_REF)


def calcular_features(raw: dict[str, Any]) -> dict[str, Any]:
    """Calcula las features derivadas a partir de datos crudos.

    Args:
        raw: Datos crudos del caso (columnas de ``cases``).

    Returns:
        Dict con las features (claves de ``FEATURE_COLUMNS``). Los campos no
        derivables de forma determinista (``comps_por_dia``, ``monto_promedio_comp``,
        ``gps_match_ok``, ``entrega_demorada``, ``score_texto``) se conservan
        si vienen precargados en ``raw``.
    """
    p = _cargar_percentiles()
    df_ref = _df_referencia()

    features: dict[str, Any] = {}

    # Riesgo financiero
    valor = max(float(raw.get("valor_orden_mxn", 0)), 1.0)
    features["comp_ratio"] = float(raw.get("compensacion_solicitada_mxn", 0)) / valor
    features["burn_rate"] = float(raw.get("monto_compensado_90d_mxn", 0)) / max(
        float(raw.get("antiguedad_usuario_dias", 0)), 1.0
    )
    features["freq_densidad"] = float(raw.get("num_compensaciones_90d", 0)) / min(
        max(float(raw.get("antiguedad_usuario_dias", 0)), 1.0), 90.0
    )

    # Inconsistencia
    features["flag_inconsistencia_gps"] = (
        raw.get("motivo_reclamo") == "Orden no llegó"
        and raw.get("entrega_confirmada_gps") in ("SÍ - confirmada", "Parcial")
    )
    features["flag_mentira_gps_alta"] = (
        raw.get("motivo_reclamo") in ("Producto incorrecto", "Producto incompleto")
        and raw.get("entrega_confirmada_gps") == "SÍ - confirmada"
        and float(raw.get("compensacion_solicitada_mxn", 0)) > p["p95_comp"]
    )
    features["flag_retraso_critico"] = (
        float(raw.get("tiempo_entrega_real_min", 0)) > p["p90_tiempo"]
    )
    features["flag_account_abuse"] = (
        float(raw.get("antiguedad_usuario_dias", 0)) < 90
        and float(raw.get("num_compensaciones_90d", 0)) > p["p95_ncomps"]
    )
    features["score_riesgo_previo"] = (
        float(raw.get("flags_fraude_previos", 0)) * 2
        + float(raw.get("num_compensaciones_90d", 0)) * 0.5
    )

    # Texto
    texto = str(raw.get("descripcion_reclamo", ""))
    features["longitud_reclamo"] = len(texto.split())
    features["flag_palabras_criticas"] = bool(PALABRAS_CRITICAS.search(texto))

    # Geográficas (tasas del dataset original)
    features["riesgo_ciudad"] = float(
        (df_ref["ciudad"] == raw.get("ciudad", "")).mean()
    )
    features["riesgo_vertical"] = float(
        (df_ref["vertical"] == raw.get("vertical", "")).mean()
    )

    # EDA-derived
    gps_ok = raw.get("entrega_confirmada_gps") == "SÍ - confirmada"
    features["gps_paradoja_score"] = (
        (0.5 if gps_ok else 0.0)
        + (0.3 if float(raw.get("num_compensaciones_90d", 0)) > p["p90_ncomps"] else 0.0)
        + (0.2 if float(raw.get("flags_fraude_previos", 0)) > 0 else 0.0)
    )
    features["sospecha_nuevo_recurrente"] = (
        float(raw.get("antiguedad_usuario_dias", 0)) < 90
        and float(raw.get("num_compensaciones_90d", 0)) >= 3
        and float(raw.get("flags_fraude_previos", 0)) >= 1
    )
    media = float(df_ref["comp_ratio"].mean())
    std = float(df_ref["comp_ratio"].std())
    features["ratio_deviation"] = (
        (features["comp_ratio"] - media) / std if std > 0 else 0.0
    )

    # Features del step 02 que solo existen si vienen precargadas
    for col in ("comps_por_dia", "monto_promedio_comp", "gps_match_ok", "entrega_demorada", "score_texto"):
        if raw.get(col) is not None:
            features[col] = raw[col]

    return features


def cargar_features(conn: connection, caso_id: str) -> dict[str, Any] | None:
    """Carga la fila de features de un caso desde la tabla ``features``.

    Args:
        conn: Conexión PostgreSQL.
        caso_id: Identificador del caso.

    Returns:
        Dict con las features (claves ``FEATURE_COLUMNS``) o ``None`` si el
        caso no tiene features persistidas.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {', '.join(FEATURE_COLUMNS)}, version FROM features WHERE caso_id = %s",
            (caso_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    features = dict(row)
    return features


def persistir_features(
    conn: connection,
    caso_id: str,
    features: dict[str, Any],
    version: str = "v1",
) -> None:
    """Persiste (upsert) las features de un caso en la tabla ``features``.

    Args:
        conn: Conexión PostgreSQL.
        caso_id: Identificador del caso.
        features: Dict con las features (claves ``FEATURE_COLUMNS``).
        version: Etiqueta del feature set (``features.version``).
    """
    columnas = ", ".join(FEATURE_COLUMNS)
    valores_placeholder = ", ".join(["%s"] * (len(FEATURE_COLUMNS) + 1))
    actualizar = ", ".join(
        [f"{c} = EXCLUDED.{c}" for c in FEATURE_COLUMNS]
    )
    parametros = [features.get(c) for c in FEATURE_COLUMNS]

    with conn.cursor() as cur:
        cur.execute(
            f"""INSERT INTO features (caso_id, {columnas}, version, updated_at)
                VALUES (%s, {valores_placeholder}, NOW())
                ON CONFLICT (caso_id) DO UPDATE SET
                    {actualizar},
                    version     = EXCLUDED.version,
                    updated_at  = NOW()""",
            [caso_id, *parametros, version],
        )
