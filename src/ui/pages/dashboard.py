"""Dashboard — KPIs, gráficos y métricas para analistas de fraude."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.ui.api_client import get_cases, get_stats


@st.cache_data(ttl=30)
def _load_stats() -> dict | None:
    return get_stats()


@st.cache_data(ttl=30)
def _load_all_cases() -> pd.DataFrame:
    """Carga todos los casos para construir gráficos agregados."""
    data = get_cases(limit=250)
    if data is None or not data.get("casos"):
        return pd.DataFrame()
    return pd.DataFrame(data["casos"])


ANTIGUEDAD_BUCKETS = {"< 30 días": (0, 30), "30–90 días": (30, 90), "90–365 días": (90, 365), "> 365 días": (365, 99999)}


def render_dashboard() -> None:
    st.title("Dashboard")

    stats = _load_stats()
    if stats is None:
        st.warning("Error de conexión con la API")
        return

    total = stats.get("total_casos", 0)
    distribucion: dict[str, int] = stats.get("distribucion", {})
    por_origen: list[dict] = stats.get("por_origen", [])
    reglas_activas: int = stats.get("reglas_activas", 0)

    # ── KPIs ──────────────────────────────────────────────────────────
    total_pct = sum(distribucion.values()) or 1
    kpis = {
        "Total de casos": total,
        "% RECHAZAR": f"{distribucion.get('RECHAZAR', 0) / total_pct * 100:.1f}%",
        "% APROBAR": f"{distribucion.get('APROBAR', 0) / total_pct * 100:.1f}%",
        "% ESCALAR": f"{distribucion.get('ESCALAR', 0) / total_pct * 100:.1f}%",
    }
    cols_kpi = st.columns(4)
    for i, (label, val) in enumerate(kpis.items()):
        cols_kpi[i].metric(label, val)

    st.markdown("---")

    # ── Gráficos (2 columnas) ────────────────────────────────────────
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("📊 Distribución por decisión")
        if distribucion:
            df_dist = pd.DataFrame({"Decisión": list(distribucion.keys()), "Casos": list(distribucion.values())})
            st.bar_chart(df_dist.set_index("Decisión"), horizontal=True)

    with col_b:
        st.subheader("📊 Reglas activas")
        st.metric("Reglas activas", reglas_activas)

    st.markdown("---")

    # ── Breakdowns desde datos crudos ─────────────────────────────────
    df_all = _load_all_cases()

    if not df_all.empty:
        col_c, col_d = st.columns(2)

        # Vertical × decisión
        with col_c:
            st.subheader("📊 Decisión × Vertical")
            if "vertical" in df_all.columns and "recomendacion_agente" in df_all.columns:
                df_v = df_all.groupby(["vertical", "recomendacion_agente"]).size().unstack(fill_value=0)
                st.bar_chart(df_v, stack=True)

        # Antigüedad buckets × decisión
        with col_d:
            st.subheader("📊 Decisión × Antigüedad")
            if "antiguedad_usuario_dias" in df_all.columns and "recomendacion_agente" in df_all.columns:
                df_a = df_all.copy()
                df_a["bucket_antiguedad"] = pd.cut(
                    df_a["antiguedad_usuario_dias"].fillna(0).astype(float),
                    bins=[0, 30, 90, 365, 99999],
                    labels=["<30d", "30-90d", "90-365d", ">365d"],
                )
                df_ab = df_a.groupby(["bucket_antiguedad", "recomendacion_agente"], observed=False).size().unstack(fill_value=0)
                st.bar_chart(df_ab, stack=True)

        st.markdown("---")

        st.markdown("---")

        # Top 10 recientes
        st.subheader("📋 Últimos casos analizados")
        df_recent = df_all.sort_values("caso_id", ascending=False).head(10)
        cols_show = ["caso_id", "ciudad", "vertical", "recomendacion_agente", "flags_fraude_previos"]
        cols_show = [c for c in cols_show if c in df_recent.columns]
        st.dataframe(df_recent[cols_show], use_container_width=True, hide_index=True)

    # ── Origen ─────────────────────────────────────────────────────────
    with st.expander("Desglose por origen (original vs sintético)", expanded=False):
        incluir = st.checkbox("Incluir sintéticos", value=True)
        filtrados = [o for o in por_origen if incluir or not o.get("es_sintetico")]
        if filtrados:
            df_orig = pd.DataFrame(filtrados)
            pivot = df_orig.pivot_table(index="es_sintetico", columns="recomendacion", values="n", fill_value=0, aggfunc="sum")
            st.dataframe(pivot, use_container_width=True)

    # ── Reglas activas ─────────────────────────────────────────────────
    st.metric("Reglas activas", reglas_activas)


render_dashboard()
