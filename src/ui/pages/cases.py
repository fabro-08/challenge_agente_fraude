"""Explorar Casos — tabla con selección robusta y visor de texto."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.ui.api_client import analyze_case, get_case_detail, get_cases

COLOR_MAP: dict[str, str] = {
    "APROBAR": "#28a745",
    "RECHAZAR": "#dc3545",
    "ESCALAR": "#fd7e14",
    "PENDIENTE": "#6c757d",
}

STORE_KEY = "cases_selected_id"


@st.cache_data(ttl=30)
def _load_cases(**filtros: object) -> dict | None:
    params = {k: v for k, v in filtros.items() if v is not None and v != "" and v != "Todos"}
    return get_cases(**params)


@st.cache_data(ttl=60)
def _load_case_detail(case_id: str) -> dict | None:
    return get_case_detail(case_id)


def _color_badge(decision: str) -> str:
    color = COLOR_MAP.get(decision, "#6c757d")
    return f'<span style="background-color:{color};color:white;padding:2px 8px;border-radius:4px;font-weight:bold">{decision}</span>'


def render_cases() -> None:
    st.title("Explorar Casos")

    # Inicializar session_state
    if STORE_KEY not in st.session_state:
        st.session_state[STORE_KEY] = None

    # ── Filtros ────────────────────────────────────────────────────────
    with st.expander("Filtros", expanded=True):
        col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)
        with col_f1:
            recomendacion = st.selectbox("Recomendación", ["Todos", "APROBAR", "RECHAZAR", "ESCALAR", "PENDIENTE"], key="f_rcmd")
        with col_f2:
            ciudad = st.text_input("Ciudad", key="f_ciudad")
        with col_f3:
            origen = st.selectbox("Origen", ["Todos", "originales", "sintéticos"], key="f_origen")
        with col_f4:
            limit = st.slider("Límite", 10, 200, 50, 10, key="f_limit")
        with col_f5:
            # Selector explícito como fallback (siempre funciona)
            pass

    rec_filter = recomendacion if recomendacion != "Todos" else None
    sint_map = {"Todos": None, "originales": False, "sintéticos": True}
    data = _load_cases(recomendacion=rec_filter, ciudad=ciudad if ciudad else None, es_sintetico=sint_map.get(origen), limit=limit)

    if data is None:
        st.warning("Error de conexión con la API")
        return

    total = data.get("total", 0)
    casos: list[dict] = data.get("casos", [])
    st.caption(f"{total} casos encontrados (mostrando {len(casos)})")

    if not casos:
        st.info("No hay casos que coincidan con los filtros")
        return

    # ── Tabla ──────────────────────────────────────────────────────────
    df_casos = pd.DataFrame(casos)
    columnas = ["caso_id", "ciudad", "vertical", "valor_orden_mxn", "compensacion_solicitada_mxn", "flags_fraude_previos", "recomendacion_agente", "justificacion", "has_llm"]
    columnas = [c for c in columnas if c in df_casos.columns]
    df_display = df_casos[columnas].copy()

    df_display["valor_orden_mxn"] = df_display["valor_orden_mxn"].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "N/A")
    df_display["compensacion_solicitada_mxn"] = df_display["compensacion_solicitada_mxn"].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "N/A")
    if "justificacion" in df_display.columns:
        df_display["justificacion"] = df_display["justificacion"].apply(lambda x: (str(x)[:80] + "…") if pd.notna(x) and x else "")
    if "has_llm" in df_display.columns:
        df_display["has_llm"] = df_display["has_llm"].apply(lambda x: "🤖" if x else "")

    column_config = {
        "recomendacion_agente": st.column_config.Column("Decisión"),
        "justificacion": st.column_config.Column("Justificación"),
        "has_llm": st.column_config.Column("LLM", help="🤖 = tiene análisis"),
    }

    st.dataframe(
        df_display,
        column_config=column_config,
        use_container_width=True,
        hide_index=True,
    )

    # ── Selección via selectbox (confiable en st.navigation) ───────────
    ids = df_casos["caso_id"].astype(str).tolist()
    current = st.session_state.get(STORE_KEY)
    default_idx = ids.index(str(current)) if current and str(current) in ids else 0

    st.selectbox(
        "Seleccioná un caso para ver el detalle 👇",
        ids,
        index=default_idx,
        key=STORE_KEY,
        placeholder="Elegí un caso…",
    )

    # ── Renderizar texto del caso seleccionado ─────────────────────────
    if st.session_state[STORE_KEY]:
        _render_text_card(str(st.session_state[STORE_KEY]))


# ── Visor de texto: justificación + LLM + descripción ──────────────────


def _render_text_card(case_id: str) -> None:
    st.divider()

    detail = _load_case_detail(case_id)
    if detail is None:
        st.warning("Error al cargar el detalle del caso")
        return

    caso: dict = detail.get("caso", {})
    llm_resultado = detail.get("llm_resultado")
    checklist: list[dict] = detail.get("checklist", [])

    decision = caso.get("recomendacion_agente", "PENDIENTE")

    # Header
    col_h1, col_h2 = st.columns([4, 1])
    with col_h1:
        st.markdown(f"**{case_id}**  {_color_badge(decision)}", unsafe_allow_html=True)
    with col_h2:
        if st.button("🔄 Re-analizar", key=f"ra_{case_id}", use_container_width=True):
            with st.spinner("Ejecutando pipeline…"):
                result = analyze_case(case_id)
            if result:
                st.success(f"Análisis completado: {result.get('final_decision', 'N/A')}")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Error al re-analizar")

    # Justificación
    justificacion = caso.get("justificacion", "")
    if justificacion:
        st.markdown("📝 **Justificación**")
        st.info(justificacion)

    # LLM
    if llm_resultado and isinstance(llm_resultado, dict) and llm_resultado.get("resumen"):
        st.markdown("🤖 **Análisis del LLM**")
        resumen = llm_resultado.get("resumen", "")
        if resumen:
            st.markdown("📝 _Resumen_")
            st.info(resumen)
        veredicto = llm_resultado.get("veredicto", "")
        if veredicto:
            st.markdown("🏷️ _Veredicto_")
            st.markdown(f"> {veredicto}")
        señales = llm_resultado.get("señales_explicadas", [])
        if señales:
            st.markdown("🔍 _Señales_")
            peso_icono = {"alto": "🔴", "medio": "🟡", "bajo": "🟢"}
            for s in señales:
                peso = s.get("peso", "medio").lower()
                icono = peso_icono.get(peso, "⚪")
                st.markdown(f"{icono} **{s.get('señal', '')}** · _{peso}_  \n{s.get('explicacion', '')}")
    elif decision == "ESCALAR":
        st.caption("ℹ️ Este caso fue escalado. Usa *Re-analizar* para generar el análisis del LLM.")

    # Descripción reclamo
    descripcion = caso.get("descripcion_reclamo", "")
    if descripcion:
        st.markdown("📝 **Descripción del reclamo**")
        st.write(descripcion)

    # Datos completos (colapsado)
    with st.expander("📋 Datos completos y checklist de reglas", expanded=False):
        st.markdown(
            """
            <style>
              [data-testid="stExpander"] [data-testid="stMetricLabel"] { font-size: 0.8rem; }
              [data-testid="stExpander"] [data-testid="stMetricValue"] { font-size: 1.0rem; }
            </style>
            """,
            unsafe_allow_html=True,
        )
        cols_principal = ["usuario_id", "ciudad", "vertical", "valor_orden_mxn", "compensacion_solicitada_mxn", "flags_fraude_previos", "num_compensaciones_90d", "antiguedad_usuario_dias", "motivo_reclamo", "entrega_confirmada_gps"]
        cols_datos = st.columns(3)
        for i, campo in enumerate(cols_principal):
            valor = caso.get(campo, "N/A")
            if isinstance(valor, float):
                valor = f"{valor:.2f}"
            cols_datos[i % 3].metric(campo, valor)

        if checklist:
            st.markdown("**Checklist de reglas**")
            df_check = pd.DataFrame(checklist)
            if not df_check.empty:
                cols_check = ["regla_id", "version", "nombre", "tipo_regla", "se_disparo", "valor_actual", "detalle"]
                df_check = df_check[cols_check].copy()
                df_check["se_disparo"] = df_check["se_disparo"].apply(lambda x: "✓" if x else "✗")
                st.dataframe(df_check, use_container_width=True, hide_index=True)
        else:
            st.info("Sin checklist de reglas")


render_cases()
