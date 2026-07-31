"""Nodo compute_features: ejecuta FeatureEngineer sobre los datos crudos."""

import re
from pathlib import Path

import pandas as pd

from src.pipeline.state import CaseState

PALABRAS_CRITICAS = re.compile(
    r"alergi|intoxic|polic[ií]a|sangre|insult|denunci|abogado|demanda|hospital|veneno",
    re.IGNORECASE,
)


def _cargar_percentiles() -> dict[str, float]:
    """Carga los percentiles de referencia del dataset con features.

    Returns:
        Diccionario con p90_tiempo, p95_comp, p95_ncomps, p90_ncomps.
    """
    df = pd.read_parquet(
        Path(__file__).resolve().parents[2] / "data" / "casos_con_features.parquet"
    )
    return {
        "p90_tiempo": float(df["tiempo_entrega_real_min"].quantile(0.90)),
        "p95_comp": float(df["compensacion_solicitada_mxn"].quantile(0.95)),
        "p95_ncomps": float(df["num_compensaciones_90d"].quantile(0.95)),
        "p90_ncomps": float(df["num_compensaciones_90d"].quantile(0.90)),
    }


def compute_features(state: CaseState) -> CaseState:
    """Calcula las 16 features a partir de raw_data.

    Si raw_data ya tiene features (vino de la DB), las usa directamente.

    Args:
        state: Estado con ``raw_data``.

    Returns:
        Estado actualizado con ``features``.
    """
    raw = state["raw_data"]

    # Si ya tiene features (viene de DB con step 02 aplicado), usarlas directamente
    if raw.get("comp_ratio") is not None:
        state["features"] = raw
        return state

    # Calcular features desde cero (para casos nuevos sin step 02)
    percentiles = _cargar_percentiles()
    p = percentiles

    features = dict(raw)

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
    df_ref = pd.read_parquet(
        Path(__file__).resolve().parents[2] / "data" / "casos_con_features.parquet"
    )
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

    state["features"] = features
    return state
