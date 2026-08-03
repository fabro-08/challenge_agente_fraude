"""Dashboard — KPIs, gráficos y métricas para analistas de fraude."""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from src.ui.api_client import (
    analyze_batch,
    descargar_excel_job,
    download_excel,
    download_politicas,
    get_cases,
    get_job_resultados,
    get_job_status,
    get_stats,
)
from src.ui.flow import proceso_agente_html

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@st.cache_data(ttl=30)
def _load_stats() -> dict | None:
    return get_stats()


@st.cache_data(ttl=30)
def _load_all_cases() -> pd.DataFrame:
    """Carga todos los casos para construir gráficos agregados.

    El API pagina en bloques de 200; itera con offset hasta cubrir el total.
    """
    frames: list[pd.DataFrame] = []
    offset = 0
    total: int | None = None

    while True:
        data = get_cases(limit=200, offset=offset)
        if data is None:
            break
        if total is None:
            total = data.get("total", 0)
        casos = data.get("casos", [])
        if not casos:
            break
        frames.append(pd.DataFrame(casos))
        offset += len(casos)
        if offset >= (total or 0):
            break

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


ANTIGUEDAD_BUCKETS = {"< 30 días": (0, 30), "30–90 días": (30, 90), "90–365 días": (90, 365), "> 365 días": (365, 99999)}


def render_dashboard() -> None:
    st.title("Dashboard")

    stats = _load_stats()
    if stats is None:
        st.warning("Error de conexión con la API")
        return

    por_origen: list[dict] = stats.get("por_origen", [])
    reglas_yaml: int = stats.get("reglas_yaml", 0)

    df_all = _load_all_cases()

    # ── Filtro por origen ─────────────────────────────────────────────
    col_orig, col_sint = st.columns(2)
    incluir_originales = col_orig.checkbox("Casos originales (150)", value=True)
    incluir_sinteticos = col_sint.checkbox("Casos sintéticos (100)", value=True)

    if df_all.empty:
        st.warning("No se pudieron cargar los casos (¿la API está disponible?).")
        return

    seleccion: list[bool] = []
    if incluir_originales:
        seleccion.append(False)
    if incluir_sinteticos:
        seleccion.append(True)

    df_filt = df_all[df_all["es_sintetico"].isin(seleccion)] if seleccion else df_all.iloc[0:0]
    if not seleccion:
        st.warning("Seleccioná al menos un origen para ver el dashboard.")

    # ── KPIs ──────────────────────────────────────────────────────────
    total = int(df_filt.shape[0])
    distribucion = df_filt["recomendacion_agente"].dropna().value_counts().to_dict()
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
        st.subheader("📊 Reglas YAML")
        st.metric("Reglas YAML", reglas_yaml)

    st.markdown("---")

    # ── Breakdowns desde datos crudos ─────────────────────────────────
    if not df_filt.empty:
        df_proc = df_filt.dropna(subset=["recomendacion_agente"])

        if df_proc.empty:
            st.info("Todavía no hay casos procesados. Usá el batch para procesar casos.")
        else:
            col_c, col_d = st.columns(2)

            # Vertical × decisión
            with col_c:
                st.subheader("📊 Decisión × Vertical")
                if "vertical" in df_proc.columns and "recomendacion_agente" in df_proc.columns:
                    df_v = df_proc.groupby(["vertical", "recomendacion_agente"]).size().unstack(fill_value=0)
                    if not df_v.empty:
                        st.bar_chart(df_v, stack=True)
                    else:
                        st.caption("Sin datos para graficar.")

            # Antigüedad buckets × decisión
            with col_d:
                st.subheader("📊 Decisión × Antigüedad")
                if "antiguedad_usuario_dias" in df_proc.columns and "recomendacion_agente" in df_proc.columns:
                    df_a = df_proc.copy()
                    df_a["bucket_antiguedad"] = pd.cut(
                        df_a["antiguedad_usuario_dias"].fillna(0).astype(float),
                        bins=[0, 30, 90, 365, 99999],
                        labels=["<30d", "30-90d", "90-365d", ">365d"],
                    )
                    df_ab = df_a.groupby(["bucket_antiguedad", "recomendacion_agente"], observed=True).size().unstack(fill_value=0)
                    if not df_ab.empty:
                        st.bar_chart(df_ab, stack=True)
                    else:
                        st.caption("Sin datos para graficar.")

        st.markdown("---")

    # ── Desglose por origen ───────────────────────────────────────────
    st.subheader("📊 Desglose por origen")
    if por_origen:
        df_orig = pd.DataFrame(por_origen)
        pivot = df_orig.pivot_table(
            index="es_sintetico", columns="recomendacion", values="n", fill_value=0, aggfunc="sum"
        )
        pivot = pivot.rename(index={False: "Originales", True: "Sintéticos"})
        if pivot.shape[1] == 0:
            st.caption("Sin casos procesados todavía.")
        else:
            st.dataframe(pivot, width="stretch")

    render_entregables()
    render_proceso_agente()
    render_batch_demo()


@st.cache_data(ttl=60)
def _descargar_excel_cacheado(es_sintetico: bool) -> tuple[str, bytes] | None:
    return download_excel(es_sintetico=es_sintetico)


@st.cache_data(ttl=300)
def _descargar_politicas_cacheado() -> tuple[str, str] | None:
    return download_politicas()


def render_entregables() -> None:
    """Entregables descargables para el equipo CX (Excel y políticas)."""
    st.markdown("---")
    st.subheader(":material/file_download: Entregables")
    st.caption("Descarga los resultados del análisis listos para el equipo de CX.")

    col_e, col_f, col_g = st.columns(3)
    with col_e:
        item = _descargar_excel_cacheado(False)
        if item:
            st.download_button(
                "Excel — 150 casos originales",
                data=item[1],
                file_name=item[0],
                mime=XLSX_MIME,
                width="stretch",
            )
        else:
            st.caption("Excel no disponible")
    with col_f:
        item = _descargar_excel_cacheado(True)
        if item:
            st.download_button(
                "Excel — 250 (orig. + sintéticos)",
                data=item[1],
                file_name=item[0],
                mime=XLSX_MIME,
                width="stretch",
            )
        else:
            st.caption("Excel no disponible")
    with col_g:
        item = _descargar_politicas_cacheado()
        if item:
            st.download_button(
                "Políticas de decisión",
                data=item[1],
                file_name=item[0],
                mime="text/markdown",
                width="stretch",
            )
        else:
            st.caption("Políticas no disponibles")

    st.markdown(
        "Documentación interactiva de la API: [`http://localhost:8000/docs`](http://localhost:8000/docs)"
    )


def render_proceso_agente() -> None:
    """Grafo del proceso del agente (pipeline de decisión LangGraph).

    Diagrama estático HTML/CSS (offline, sin deps) del flujo:
    ``load_case → features → apply_rules`` y las tres vías de decisión
    (reglas APROBAR/RECHAZAR, ESCALAR forzoso y AMBIGUO). Fuente de verdad
    en ``src/pipeline/graph.py``.
    """
    st.markdown("---")
    st.subheader(":material/hub: Proceso del Agente")
    st.caption(
        "Pipeline de decisión LangGraph. Las reglas deciden APROBAR/RECHAZAR sin LLM; "
        "el ESCALAR forzoso y el caso ambiguo pasan por el LLM. Detalle en `src/pipeline/graph.py`."
    )
    st.html(proceso_agente_html())


def render_batch_demo() -> None:
    """Batch: corre el pipeline sobre casos en segundo plano.

    Por defecto es modo demo (``persistir=false``): ``resolution_case`` no se
    modifica y podés descargar el Excel del job. Con "Persistir en DB" activado
    escribe en ``resolution_case`` igual que ``POST /analyze/batch`` normal.
    """
    st.markdown("---")
    st.subheader(":material/experiment: Batch")
    st.caption(
        "Corre el pipeline sobre casos en segundo plano. Por defecto **no escribe "
        "en la base** (`persistir=false`): `resolution_case` no se modifica y podés "
        "descargar el Excel del job."
    )

    with st.container(border=True):
        # ── Origen ────────────────────────────────────────────────────
        col_o1, col_o2 = st.columns(2)
        incluir_originales = col_o1.checkbox("Casos originales (150)", value=True, key="batch_origen_orig")
        incluir_sinteticos = col_o2.checkbox("Casos sintéticos (100)", value=True, key="batch_origen_sint")

        if incluir_originales and incluir_sinteticos:
            es_sintetico: bool | None = None
        elif incluir_originales:
            es_sintetico = False
        elif incluir_sinteticos:
            es_sintetico = True
        else:
            es_sintetico = None

        modo = st.segmented_control(
            "Selección de casos",
            options=["Todos", "Puntuales", "Aleatorios"],
            default="Todos",
            key="batch_demo_modo",
        )
        col_h, col_i = st.columns(2)
        with col_h:
            if modo == "Puntuales":
                df_all = _load_all_cases()
                if es_sintetico is None:
                    opciones = sorted(df_all["caso_id"].unique().tolist()) if not df_all.empty else []
                else:
                    opciones = (
                        sorted(df_all.loc[df_all["es_sintetico"] == es_sintetico, "caso_id"].unique().tolist())
                        if not df_all.empty
                        else []
                    )
                seleccion = st.multiselect(
                    "Casos",
                    options=opciones,
                    default=opciones[:3] if len(opciones) >= 3 else opciones,
                    max_selections=10,
                    key="batch_demo_casos",
                )
            elif modo == "Aleatorios":
                limite = st.number_input(
                    "Cantidad (aleatoria)", min_value=1, max_value=50, value=5, key="batch_demo_limite"
                )
            else:
                st.caption("Procesará **todos** los casos que matcheen origen y estado pendiente.")

        with col_i:
            solo_pendientes = st.toggle(
                "Solo casos pendientes",
                value=True,
                key="batch_demo_pendientes",
                help="Solo casos sin resolución en resolution_case.",
            )
            persistir = st.toggle(
                "Persistir en DB (no demo)",
                value=False,
                key="batch_demo_persistir",
                help="Activado escribe en resolution_case (igual a POST /analyze/batch normal).",
            )
            lanzar = st.button(":material/play_arrow: Lanzar batch", type="primary", key="batch_demo_lanzar")

        if lanzar:
            if not (incluir_originales or incluir_sinteticos):
                st.warning("Seleccioná al menos un origen.")
            elif modo == "Puntuales":
                if not seleccion:
                    st.warning("Seleccioná al menos un caso.")
                else:
                    resp = analyze_batch(case_ids=seleccion, persistir=persistir)
            elif modo == "Aleatorios":
                resp = analyze_batch(
                    es_sintetico=es_sintetico,
                    solo_pendientes=solo_pendientes,
                    limite=int(limite),
                    aleatorio=True,
                    persistir=persistir,
                )
            else:  # Todos
                resp = analyze_batch(
                    es_sintetico=es_sintetico,
                    solo_pendientes=solo_pendientes,
                    persistir=persistir,
                )
            if resp:
                st.session_state["batch_demo_job"] = resp["job_id"]
                st.rerun()
            else:
                st.error("No se pudo lanzar el batch (¿la API está disponible?).")

    job_id = st.session_state.get("batch_demo_job")
    if not job_id:
        return
    _render_batch_progreso(job_id)


def _render_batch_progreso(job_id: str) -> None:
    """Hace polling al job y muestra progreso/resultados de la demo."""
    estado = get_job_status(job_id)
    if estado is None:
        st.warning(f"No se encontró el job {job_id}.")
        st.session_state.pop("batch_demo_job", None)
        return

    if estado["status"] == "running":
        total = max(estado["total"], 1)
        st.progress(
            estado["procesados"] / total,
            text=f"Procesando… {estado['procesados']}/{estado['total']} casos",
        )
        st.caption(f"Errores: {estado['errores']}")
        time.sleep(2)
        st.rerun()

    if estado["status"] == "error":
        st.error(
            "El batch excedió el tiempo máximo permitido y se detuvo. "
            "Revisá la API o aumentá JOBS_MAX_TIMEOUT_S / CASO_TIMEOUT_S."
        )
        st.session_state.pop("batch_demo_job", None)
        return

    if estado["total"] == 0:
        st.warning("No hay casos que cumplan los criterios (revisá origen / solo pendientes).")
    st.success(f"Batch terminado — distribución: {estado['decisiones']}")
    resultados = get_job_resultados(job_id)
    if resultados and resultados.get("resultados"):
        df_demo = pd.DataFrame(resultados["resultados"])
        cols = [
            c
            for c in ["caso_id", "recomendacion", "fuente", "decision_regla", "decision_llm", "resumen_llm"]
            if c in df_demo.columns
        ]
        st.dataframe(df_demo[cols], width="stretch", hide_index=True)
        item = descargar_excel_job(job_id)
        if item:
            st.download_button(
                ":material/download: Excel de esta demo",
                data=item[1],
                file_name=item[0],
                mime=XLSX_MIME,
                width="stretch",
            )
    else:
        st.caption("Sin filas (el job no usó modo memoria o no procesó casos).")
    st.session_state.pop("batch_demo_job", None)


render_dashboard()
