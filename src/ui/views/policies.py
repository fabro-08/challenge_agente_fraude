"""Políticas de Decisión — thresholds y reglas de negocio."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


def render_policies() -> None:
    """Renderiza la página de Políticas de Decisión."""
    st.title("Políticas de Decisión")

    # ── Documento de políticas ─────────────────────────────────────────
    docs_dir = Path(__file__).resolve().parent.parent.parent.parent / "docs"
    md_path = docs_dir / "politicas_decision.md"

    if md_path.exists():
        with open(md_path, "r", encoding="utf-8") as f:
            contenido = f.read()
        st.markdown(contenido)
    else:
        st.warning(f"No se encontró el archivo de políticas: {md_path}")

    # ── Thresholds actuales ────────────────────────────────────────────
    st.divider()
    st.subheader("Thresholds actuales")

    thresholds_data = [
        ("Flags de fraude previos (R1)", "≥ 2", "flags_fraude_previos"),
        ("Comp ratio desproporcionado (R2)", "> 0.99", "comp_ratio"),
        ("Frecuencia de reclamos anómala (R3)", "> 0.66", "freq_densidad"),
        ("Compensación > p99 (R4)", "> 604.64 MXN", "compensacion_solicitada_mxn"),
        ("Inconsistencia GPS (R5)", "True", "flag_inconsistencia_gps"),
        ("Cuenta nueva con abuso (R6)", "< 90 días + reclamos > p95", "flag_account_abuse"),
        ("Score de riesgo previo (R7)", "> 10.0", "score_riesgo_previo"),
        ("Retraso crítico + motivo coherente (A1)", "tiempo_entrega > 96 min", "flag_retraso_critico"),
        ("Usuario sano / perfil conservador (A2)", "flags=0, comp_ratio≤0.8, antigüedad≥90d", "varios"),
        ("GPS ok + usuario antiguo (A3)", "GPS=SÍ, entrega≤96min, antigüedad≥90d", "varios"),
    ]

    df_thresholds = pd.DataFrame(
        thresholds_data,
        columns=["Regla", "Umbral", "Campo"],
    )
    st.dataframe(df_thresholds, width="stretch", hide_index=True)
render_policies()
