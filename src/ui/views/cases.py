"""Explorar Casos — tabla con selección por fila y panel de detalle.

Auto-paginación (sin límite manual): el API pagina en bloques de 200; el
navegador de páginas usa ``st.pagination``. Al hacer clic en una fila se
renderiza el detalle debajo: features del caso, semáforo del checklist de
reglas y el resultado del LLM (cuando aplica).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.ui.api_client import analyze_case, get_case_detail, get_cases, get_rules

COLOR_MAP: dict[str, str] = {
    "APROBAR": "#28a745",
    "RECHAZAR": "#dc3545",
    "ESCALAR": "#fd7e14",
    "PENDIENTE": "#6c757d",
}

ORIGEN_LABEL: dict[str, str] = {
    "reglas": "Regla",
    "llm": "LLM",
}

TIPO_REGLA_COLOR: dict[str, str] = {
    "RECHAZAR": "#dc3545",
    "APROBAR": "#28a745",
    "ESCALAR_FORZOSO": "#fd7e14",
}

PAGE_SIZE = 200
STORE_KEY = "cases_selected_id"
PAGE_KEY = "cases_page"

# Features de la grilla de detalle: derivadas (features) + montos/datos del caso.
# Incluye los campos pedidos explícitamente por negocio (antigüedad, comp.
# solicitada, compensaciones 90d, entrega GPS, flags) aunque participen en reglas.
# Excluye columnas sin datos (comps_por_dia, monto_promedio_comp, gps_match_ok, ...).
FEATURES_GRID: list[tuple[str, str]] = [
    ("burn_rate", "Burn rate"),
    ("ratio_deviation", "Ratio desviación"),
    ("riesgo_ciudad", "Riesgo ciudad"),
    ("riesgo_vertical", "Riesgo vertical"),
    ("gps_paradoja_score", "Paradoja GPS"),
    ("longitud_reclamo", "Long. reclamo (palabras)"),
    ("flag_mentira_gps_alta", "Mentira GPS alta"),
    ("flag_palabras_criticas", "Palabras críticas"),
    ("sospecha_nuevo_recurrente", "Nuevo recurrente"),
    ("valor_orden_mxn", "Valor orden (MXN)"),
    ("compensacion_solicitada_mxn", "Comp. solicitada (MXN)"),
    ("monto_compensado_90d_mxn", "Compensado 90d (MXN)"),
    ("num_compensaciones_90d", "Compensaciones 90d"),
    ("tiempo_entrega_real_min", "Tiempo entrega (min)"),
    ("antiguedad_usuario_dias", "Antigüedad (días)"),
    ("flags_fraude_previos", "Flags fraude previos"),
    ("entrega_confirmada_gps", "Entrega GPS confirmada"),
]

# Umbrales de referencia para el semáforo de la grilla (visual-only).
# Fuente: src/rules/thresholds.yaml.
UMBRAL_TIEMPO_ENTREGA_MIN = 96
UMBRAL_ANTIGUEDAD_MIN = 90
UMBRAL_COMPENSACION_P99 = 604.64
UMBRAL_COMPS_90D_MAX = 2
UMBRAL_FLAGS_MIN = 2


@st.cache_data(ttl=30)
def _load_cases(**filtros: object) -> dict | None:
    params = {k: v for k, v in filtros.items() if v is not None and v != "" and v != "Todos"}
    return get_cases(**params)


@st.cache_data(ttl=60)
def _load_case_detail(case_id: str) -> dict | None:
    return get_case_detail(case_id)


@st.cache_data(ttl=300)
def _load_prioridades() -> dict[str, int]:
    """Mapa regla_id → prioridad (configuracion_reglas) para ordenar el checklist."""
    reglas = get_rules()
    if not isinstance(reglas, list):
        return {}
    return {r["regla_id"]: int(r["prioridad"]) for r in reglas if r.get("regla_id")}


def _color_badge(decision: str) -> str:
    color = COLOR_MAP.get(decision, "#6c757d")
    return f'<span style="background-color:{color};color:white;padding:2px 8px;border-radius:4px;font-weight:bold">{decision}</span>'


def _estilo_checklist(df_check: pd.DataFrame) -> pd.DataFrame.style:
    """Semaforiza el checklist: color por tipo de regla y resalta las disparadas."""

    def _celda_fila(row: pd.Series) -> list[str]:
        estilos: list[str] = []
        for col in df_check.columns:
            if col == "tipo_regla":
                estilos.append(f"color: {TIPO_REGLA_COLOR.get(row[col], '#6c757d')}; font-weight: 700;")
            elif col == "se_disparo":
                disparado = row[col] == "✅"
                estilos.append(
                    f"color: {'#28a745' if disparado else '#8b949e'}; font-weight: 700;"
                )
            else:
                estilos.append("")
        return estilos

    def _fondo_disparada(row: pd.Series) -> list[str]:
        if row["se_disparo"] == "✅":
            return ["background-color: rgba(40, 167, 69, 0.12);"] * len(df_check.columns)
        return [""] * len(df_check.columns)

    return df_check.style.apply(_fondo_disparada, axis=1).apply(_celda_fila, axis=1)


def _estilo_tabla(df: pd.DataFrame) -> pd.DataFrame.style:
    """Colorea la columna 'origen' y 'decision' de la tabla de casos."""

    def _celda_fila(row: pd.Series) -> list[str]:
        estilos: list[str] = []
        for col in df.columns:
            if col == "origen":
                color = {"Regla": "#8b5cf6", "LLM": "#2563eb"}.get(row[col], "#6c757d")
                estilos.append(f"color: {color}; font-weight: 700;")
            elif col == "decision":
                estilos.append(f"color: {COLOR_MAP.get(row[col], '#6c757d')}; font-weight: 700;")
            else:
                estilos.append("")
        return estilos

    return df.style.apply(_celda_fila, axis=1)


def _format_valor(v: object) -> str:
    """Formatea un valor de feature para la grilla de detalle."""
    if v is None:
        return "N/A"
    if isinstance(v, bool):
        return "Sí" if v else "No"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def _sem_color(campo: str, valor: object) -> str | None:
    """Color de semáforo (rojo=riesgo / verde=ok) si existe umbral de referencia."""
    if campo == "flag_palabras_criticas" and isinstance(valor, bool):
        return "#dc3545" if valor else "#28a745"
    if campo == "tiempo_entrega_real_min" and isinstance(valor, (int, float)):
        return "#dc3545" if valor > UMBRAL_TIEMPO_ENTREGA_MIN else "#28a745"
    if campo == "antiguedad_usuario_dias" and isinstance(valor, (int, float)):
        return "#dc3545" if valor < UMBRAL_ANTIGUEDAD_MIN else "#28a745"
    if campo == "compensacion_solicitada_mxn" and isinstance(valor, (int, float)):
        return "#dc3545" if valor > UMBRAL_COMPENSACION_P99 else "#28a745"
    if campo == "num_compensaciones_90d" and isinstance(valor, (int, float)):
        return "#dc3545" if valor > UMBRAL_COMPS_90D_MAX else "#28a745"
    if campo == "flags_fraude_previos" and isinstance(valor, (int, float)):
        return "#dc3545" if valor >= UMBRAL_FLAGS_MIN else "#28a745"
    return None


def _render_features(caso: dict) -> None:
    """Grilla de features del caso en tarjetas compactas (letra pequeña)."""
    st.markdown(":material/query_stats: **Features del caso**")
    cards: list[str] = []
    for campo, label in FEATURES_GRID:
        valor = _format_valor(caso.get(campo))
        color = _sem_color(campo, caso.get(campo))
        style = f"color:{color};font-weight:700;" if color else ""
        cards.append(
            f'<div style="background:rgba(128,128,128,0.08);border-radius:8px;'
            f'padding:6px 10px;min-width:210px;flex:1;">'
            f'<div style="font-size:0.68rem;color:rgba(128,128,128,0.9);'
            f'text-transform:uppercase;letter-spacing:.03em;">{label}</div>'
            f'<div style="font-size:0.95rem;{style}">{valor}</div>'
            f"</div>"
        )
    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;gap:8px;">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def render_cases() -> None:
    st.title("Explorar casos")

    if STORE_KEY not in st.session_state:
        st.session_state[STORE_KEY] = None

    # ── Filtros ────────────────────────────────────────────────────────
    with st.expander("Filtros", expanded=True):
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            recomendacion = st.selectbox(
                "Recomendación",
                ["Todos", "APROBAR", "RECHAZAR", "ESCALAR", "PENDIENTE"],
                key="f_rcmd",
            )
        with col_f2:
            ciudad = st.text_input("Ciudad", key="f_ciudad")
        with col_f3:
            dataset = st.selectbox("Dataset", ["Todos", "originales", "sintéticos"], key="f_origen")

    rec_filter = recomendacion if recomendacion != "Todos" else None
    sint_map = {"Todos": None, "originales": False, "sintéticos": True}
    filtros = {
        "recomendacion": rec_filter,
        "ciudad": ciudad if ciudad else None,
        "es_sintetico": sint_map.get(dataset),
    }

    # ── Auto-paginación (200 por página, sin límite manual) ────────────
    probe = _load_cases(limit=PAGE_SIZE, offset=0, **filtros)
    if probe is None:
        st.warning("Error de conexión con la API")
        return

    total = probe.get("total", 0)
    num_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = st.pagination(num_pages, default=st.session_state.get(PAGE_KEY, 1), key=PAGE_KEY)

    offset = (page - 1) * PAGE_SIZE
    data = _load_cases(limit=PAGE_SIZE, offset=offset, **filtros)
    casos: list[dict] = data.get("casos", []) if data else []
    st.caption(f"{total} casos encontrados · página {page} de {num_pages}")

    if not casos:
        st.info("No hay casos que coincidan con los filtros")
        return

    # ── Tabla con selección por fila ───────────────────────────────────
    df_casos = pd.DataFrame(casos)
    columnas = [
        "caso_id",
        "usuario_id",
        "ciudad",
        "vertical",
        "restaurante",
        "fuente",
        "recomendacion_agente",
    ]
    columnas = [c for c in columnas if c in df_casos.columns]
    df_display = df_casos[columnas].copy()

    if "fuente" in df_display.columns:
        df_display["origen"] = df_display["fuente"].map(ORIGEN_LABEL).fillna("—")
        df_display.drop(columns=["fuente"], inplace=True)
    if "recomendacion_agente" in df_display.columns:
        df_display.rename(columns={"recomendacion_agente": "decision"}, inplace=True)

    event = st.dataframe(
        _estilo_tabla(df_display),
        column_config={
            "caso_id": st.column_config.TextColumn("Caso", pinned=True),
            "usuario_id": st.column_config.TextColumn("Usuario"),
            "ciudad": st.column_config.TextColumn("Ciudad"),
            "vertical": st.column_config.TextColumn("Vertical"),
            "restaurante": st.column_config.TextColumn("Restaurante"),
            "origen": st.column_config.TextColumn("Origen"),
            "decision": st.column_config.TextColumn("Decisión"),
        },
        height=520,
        hide_index=True,
        key="cases_df",
        on_select="rerun",
        selection_mode="single-row",
    )

    # Detalle del caso seleccionado (persiste en session_state entre reruns)
    if event.selection.rows:
        idx = event.selection.rows[0]
        case_id = str(df_casos.iloc[idx]["caso_id"])
        st.session_state[STORE_KEY] = case_id
        _render_detail(case_id)
    elif st.session_state[STORE_KEY]:
        st.caption("Seleccioná un caso de la tabla para ver el detalle.")


# ── Panel de detalle ──────────────────────────────────────────────────


def _render_detail(case_id: str) -> None:
    st.divider()

    detail = _load_case_detail(case_id)
    if detail is None:
        st.warning("Error al cargar el detalle del caso")
        return

    caso: dict = detail.get("caso", {})
    llm_resultado = detail.get("llm_resultado")
    checklist: list[dict] = detail.get("checklist", [])

    decision = caso.get("recomendacion_agente", "PENDIENTE")
    fuente = caso.get("fuente", "")
    sintetico_label = "Sintético" if caso.get("es_sintetico") else "Original"
    resolucion = {"reglas": "Regla", "llm": "Agente"}.get(fuente, "—")
    resolucion_color = {"reglas": "#8b5cf6", "llm": "#2563eb"}.get(fuente, "#6c757d")

    # Header
    col_h1, col_h2 = st.columns([4, 1])
    with col_h1:
        st.markdown(
            f"**{case_id}**  |  {sintetico_label}  |  {_color_badge(decision)}  "
            f'<span style="color:{resolucion_color};font-weight:600;margin-left:8px">'
            f"Resolución: {resolucion}</span>",
            unsafe_allow_html=True,
        )
    with col_h2:
        if st.button(":material/refresh: Re-analizar", key=f"ra_{case_id}"):
            with st.spinner("Ejecutando pipeline…"):
                result = analyze_case(case_id)
            if result:
                st.success(f"Análisis completado: {result.get('final_decision', 'N/A')}")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Error al re-analizar")

    # Resultados discretos: reglas → LLM (decisión final = COALESCE)
    r_reglas = caso.get("decision_regla")
    r_llm = caso.get("decision_llm")
    if r_reglas or r_llm:
        partes = [f"Reglas: **{r_reglas or '—'}**"]
        if r_llm:
            partes.append(f"LLM: **{r_llm}**")
        st.caption(" · ".join(partes))

    # ── 1.1 Descripción del reclamo ───────────────────────────────────
    descripcion = caso.get("descripcion_reclamo", "")
    if descripcion:
        with st.container(border=True):
            st.markdown(":material/description: **Descripción del reclamo**")
            motivo = caso.get("motivo_reclamo", "")
            if motivo:
                st.markdown(
                    f'<span style="background:rgba(13,110,253,0.12);color:#0d6efd;'
                    f'border-radius:999px;padding:2px 10px;font-size:0.8rem;'
                    f'font-weight:600;">Motivo: {motivo}</span>',
                    unsafe_allow_html=True,
                )
            st.write(descripcion)

    # ── 1.2 Señales usadas (reglas vs LLM) ────────────────────────────
    senales_regla = caso.get("senales_regla", "") or ""
    senales_llm = caso.get("senales_llm", "") or ""
    if senales_regla or senales_llm:
        with st.container(border=True):
            st.markdown(":material/flag: **Señales usadas**")
            if senales_regla:
                st.markdown("_Reglas_")
                chips = "".join(
                    f'<span style="background:rgba(139,92,246,0.15);color:#8b5cf6;'
                    f'border-radius:999px;padding:2px 10px;font-size:0.8rem;'
                    f'font-weight:600;">{p}</span> '
                    for p in (x.strip() for x in senales_regla.split("|") if x.strip())
                )
                st.markdown(chips, unsafe_allow_html=True)
            if senales_llm:
                st.markdown("_LLM_")
                chips = "".join(
                    f'<span style="background:rgba(13,202,240,0.15);color:#0dcaf0;'
                    f'border-radius:999px;padding:2px 10px;font-size:0.8rem;'
                    f'font-weight:600;">{p}</span> '
                    for p in (x.strip() for x in senales_llm.split("|") if x.strip())
                )
                st.markdown(chips, unsafe_allow_html=True)

    # ── 1.2b Justificación de reglas ──────────────────────────────────
    justificacion_regla = caso.get("justificacion_regla", "") or ""
    if justificacion_regla:
        with st.container(border=True):
            st.markdown(":material/rule: **Justificación (reglas)**")
            st.write(justificacion_regla)

    # ── 1.3 Features del caso ─────────────────────────────────────────
    with st.container(border=True):
        _render_features(caso)

    # ── Semáforo de reglas ────────────────────────────────────────────
    with st.container(border=True):
        st.markdown(":material/traffic: **Checklist de reglas**")
        if checklist:
            prioridades = _load_prioridades()
            checklist = sorted(
                checklist,
                key=lambda i: (prioridades.get(i.get("regla_id"), 999), i.get("regla_id", "")),
            )
            df_check = pd.DataFrame(checklist)
            if not df_check.empty:
                cols_check = [
                    "regla_id",
                    "version",
                    "nombre",
                    "tipo_regla",
                    "se_disparo",
                    "valor_actual",
                    "detalle",
                ]
                cols_check = [c for c in cols_check if c in df_check.columns]
                df_check = df_check[cols_check].copy()
                df_check["se_disparo"] = df_check["se_disparo"].apply(lambda x: "✅" if x else "❌")
                st.dataframe(
                    _estilo_checklist(df_check),
                    column_config={"version": st.column_config.NumberColumn("Versión")},
                    hide_index=True,
                )
        else:
            st.info("Sin checklist de reglas")

    # ── Análisis del LLM ──────────────────────────────────────────────
    with st.container(border=True):
        r_llm = caso.get("decision_llm")
        header = ":material/smart_toy: **Análisis del LLM**"
        if r_llm:
            header += f"  {_color_badge(r_llm)}"
        st.markdown(header, unsafe_allow_html=True)

        if llm_resultado and isinstance(llm_resultado, dict) and llm_resultado.get("veredicto"):
            veredicto = llm_resultado.get("veredicto", "")
            if veredicto:
                st.markdown(f"> {veredicto}")
            resumen = llm_resultado.get("resumen", "")
            if resumen:
                st.markdown("_Resumen_")
                st.info(resumen)
            justificacion = caso.get("justificacion_llm", "") or ""
            if justificacion:
                st.markdown("_Justificación_")
                st.write(justificacion)
            señales = llm_resultado.get("señales_explicadas", [])
            if señales:
                st.markdown("_Señales explicadas_")
                peso_icono = {"alto": "🔴", "medio": "🟡", "bajo": "🟢"}
                for s in señales:
                    peso = s.get("peso", "medio").lower()
                    icono = peso_icono.get(peso, "⚪")
                    st.markdown(f"{icono} **{s.get('señal', '')}** · _{peso}_  \n{s.get('explicacion', '')}")
        elif decision == "ESCALAR":
            st.caption("Este caso fue escalado. Usa *Re-analizar* para generar el análisis del LLM.")
        else:
            st.caption("Este caso se resolvió con reglas; el LLM no participó.")


render_cases()
