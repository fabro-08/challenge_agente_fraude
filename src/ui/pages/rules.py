"""Reglas de Decisión — gestión de reglas, simulación e historial."""

from __future__ import annotations

import streamlit as st

from src.ui.api_client import (
    delete as api_delete,
    get_campos,
    get_case_detail,
    get_cases,
    get_rule_detail,
    get_rule_versions,
    get_rules,
    get_users,
    post,
    put,
    simulate_rules,
)

COLOR_MAP: dict[str, str] = {
    "APROBAR": "#28a745",
    "RECHAZAR": "#dc3545",
    "ESCALAR": "#fd7e14",
    "PENDIENTE": "#6c757d",
}
BADGE_COLORS: dict[str, str] = {
    "APROBAR": "green",
    "RECHAZAR": "red",
    "ESCALAR": "orange",
    "ESCALAR_FORZOSO": "orange",
    "PENDIENTE": "gray",
}


@st.cache_data(ttl=30)
def _load_rules() -> list[dict] | None:
    data = get_rules()
    return list(data) if isinstance(data, list) else None


@st.cache_data(ttl=60)
def _load_campos() -> dict | None:
    return get_campos()


@st.cache_data(ttl=30)
def _load_users() -> list[dict] | None:
    data = get_users()
    return list(data) if isinstance(data, list) else None


def _color_badge(decision: str) -> str:
    color = COLOR_MAP.get(decision, "#6c757d")
    return f'<span style="background-color:{color};color:white;padding:2px 8px;border-radius:4px;font-weight:bold">{decision}</span>'


def _render_condition_builder(
    key_prefix: str,
    condiciones_existentes: list[dict] | None = None,
) -> list[dict]:
    """Widget reusable para construir/editar condiciones de reglas."""
    campos_data = _load_campos()
    campos_disponibles: list[str] = []
    operadores_disponibles: list[str] = []

    if campos_data:
        campos_disponibles = campos_data.get("campos", [])
        operadores_disponibles = campos_data.get("operadores", [])

    if not campos_disponibles:
        st.warning("No se pudieron cargar los campos disponibles")
        return []

    condiciones = condiciones_existentes or []

    n_condiciones = st.number_input(
        "Número de condiciones",
        min_value=1,
        max_value=20,
        value=max(len(condiciones), 1),
        step=1,
        key=f"{key_prefix}_n_cond",
    )

    nuevas_condiciones: list[dict] = []

    for i in range(int(n_condiciones)):
        st.markdown(f"**Condición {i + 1}**")
        col_a, col_b, col_c = st.columns([3, 2, 3])

        existing = condiciones[i] if i < len(condiciones) else {}
        campo_default = existing.get("campo", "")
        operador_default = existing.get("operador", ">=")
        valor_default = existing.get("valor", "")

        campo_idx = campos_disponibles.index(campo_default) if campo_default in campos_disponibles else 0
        op_idx = operadores_disponibles.index(operador_default) if operador_default in operadores_disponibles else 0

        with col_a:
            campo = st.selectbox(
                "Campo",
                campos_disponibles,
                index=campo_idx,
                key=f"{key_prefix}_campo_{i}",
            )
        with col_b:
            operador = st.selectbox(
                "Operador",
                operadores_disponibles,
                index=op_idx,
                key=f"{key_prefix}_op_{i}",
            )
        with col_c:
            if operador in ("contains_any", "contains_all"):
                valor_raw = st.text_input(
                    "Valores (separados por coma)",
                    value=", ".join(valor_default) if isinstance(valor_default, list) else str(valor_default),
                    key=f"{key_prefix}_val_{i}",
                )
            else:
                valor_raw = st.text_input(
                    "Valor",
                    value=str(valor_default) if valor_default else "",
                    key=f"{key_prefix}_val_{i}",
                )

        valor_parsed = _parse_valor(valor_raw, operador)

        nuevas_condiciones.append({
            "campo": campo,
            "operador": operador,
            "valor": valor_parsed,
        })

    return nuevas_condiciones


def _parse_valor(valor_raw: str, operador: str) -> object:
    """Convierte el valor a int/float/list según el operador."""
    if not valor_raw:
        return ""
    if operador in ("contains_any", "contains_all"):
        return [v.strip() for v in valor_raw.split(",") if v.strip()]
    if operador in ("in", "not_in"):
        return [v.strip() for v in valor_raw.split(",") if v.strip()]
    raw = valor_raw.strip()
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _reglas_table(rules: list[dict]) -> str | None:
    """Muestra tabla de reglas y retorna el regla_id seleccionado."""
    import pandas as pd

    if not rules:
        st.info("No hay reglas configuradas")
        return None

    df = pd.DataFrame(rules)
    cols_display = ["regla_id", "nombre", "tipo_regla", "prioridad", "activo", "version_actual"]
    df_display = df[cols_display].copy()
    df_display["activo"] = df_display["activo"].apply(lambda x: "✓" if x else "✗")

    event = st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="rules_table",
    )

    selected = event.selection.get("rows", []) if hasattr(event, "selection") else []
    if selected:
        return str(df.iloc[selected[0]]["regla_id"])
    return None


def _render_regla_editor(regla_id: str) -> None:
    """Expander con editor de regla existente."""
    regla = get_rule_detail(regla_id)
    if regla is None:
        st.error("Error al cargar la regla")
        return

    with st.expander(f"Editar: {regla.get('nombre', regla_id)} ({regla.get('tipo_regla', '')})", expanded=True):
        config: dict = regla.get("config", {})
        condiciones_existentes: list[dict] = config.get("condiciones", [])
        match_type: str = config.get("match", "all")
        descripcion: str = config.get("descripcion", "")

        st.markdown(f"**Descripción:** {descripcion}")
        col_m1, col_m2 = st.columns([2, 4])
        with col_m1:
            nuevo_match = st.selectbox(
                "Match",
                ["all", "any"],
                index=0 if match_type == "all" else 1,
                key=f"match_{regla_id}",
            )
        with col_m2:
            st.caption("all = todas las condiciones deben cumplirse, any = al menos una")

        st.subheader("Condiciones")
        nuevas_condiciones = _render_condition_builder(
            f"edit_{regla_id}",
            condiciones_existentes,
        )

        nueva_config = {
            "descripcion": descripcion,
            "match": nuevo_match,
            "condiciones": nuevas_condiciones,
        }

        col_btn1, col_btn2, col_btn3 = st.columns([2, 2, 2])

        with col_btn1:
            if st.button("Simular impacto", key=f"sim_{regla_id}", type="secondary"):
                with st.spinner("Simulando..."):
                    sim_payload = {
                        "accion": "update",
                        "regla_id": regla_id,
                        "config": nueva_config,
                    }
                    result = simulate_rules(sim_payload)
                if result:
                    _mostrar_simulacion(result)
                else:
                    st.error("Error en la simulación")

        with col_btn2:
            if st.button("Guardar cambios", key=f"save_{regla_id}", type="primary"):
                _guardar_cambios_regla(regla_id, nueva_config)

        with col_btn3:
            activo_actual = regla.get("activo", True)
            nuevo_label = "Desactivar regla" if activo_actual else "Activar regla"
            if st.button(nuevo_label, key=f"toggle_{regla_id}"):
                users = _load_users()
                user_options = {u["nombre"]: u["nombre"] for u in users} if users else {}
                if not user_options:
                    st.error("No hay usuarios disponibles")
                    return
                selected_user = st.selectbox(
                    "Usuario responsable",
                    list(user_options.keys()),
                    key=f"toggle_user_{regla_id}",
                )
                motivo = st.text_area(
                    "Motivo del cambio",
                    key=f"toggle_motivo_{regla_id}",
                )
                if st.button("Confirmar", key=f"confirm_toggle_{regla_id}"):
                    payload: dict = {
                        "updated_by": selected_user,
                        "cambio_descripcion": motivo or ("Desactivación" if activo_actual else "Activación"),
                    }
                    if activo_actual:
                        result = api_delete(f"/rules/{regla_id}", json=payload)
                    else:
                        result = put(f"/rules/{regla_id}", json={
                            "config": regla.get("config", {}),
                            "updated_by": selected_user,
                            "cambio_descripcion": motivo or "Activación de la regla",
                            "activo": True,
                        })
                    if result:
                        st.success("Cambio aplicado")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("Error al aplicar el cambio")


def _guardar_cambios_regla(regla_id: str, nueva_config: dict) -> None:
    """Formulario y guardado de cambios en una regla."""
    users = _load_users()
    user_options = {u["nombre"]: u["nombre"] for u in users} if users else {"fraude_admin": "fraude_admin"}

    selected_user = st.selectbox(
        "Usuario responsable",
        list(user_options.keys()),
        key=f"save_user_{regla_id}",
    )
    motivo = st.text_area(
        "Descripción del cambio",
        key=f"save_motivo_{regla_id}",
        placeholder="Ej: Ajustar umbral de comp_ratio de 0.99 a 0.95",
    )

    if not motivo or len(motivo) < 5:
        st.warning("La descripción del cambio debe tener al menos 5 caracteres")
        return

    if st.button("Confirmar guardado", key=f"confirm_save_{regla_id}"):
        payload: dict = {
            "config": nueva_config,
            "updated_by": selected_user,
            "cambio_descripcion": motivo,
        }
        result = put(f"/rules/{regla_id}", json=payload)
        if result:
            st.success("Regla actualizada correctamente")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error("Error al guardar la regla")


def _mostrar_simulacion(result: dict) -> None:
    """Muestra los resultados de una simulación."""
    import pandas as pd

    st.subheader("Resultado de la simulación")
    casos_evaluados = result.get("casos_evaluados", 0)
    cambian = result.get("cambian_decision", 0)
    transiciones: dict = result.get("transiciones", {})
    afectados: list[dict] = result.get("casos_afectados", [])
    nota = result.get("nota", "")

    col_s1, col_s2 = st.columns(2)
    col_s1.metric("Casos evaluados", casos_evaluados)
    col_s2.metric("Cambian decisión", cambian, delta=None)

    if transiciones:
        st.caption(f"Transiciones: {transiciones}")

    if nota:
        st.info(nota)

    if afectados:
        st.subheader("Casos afectados")
        df_af = pd.DataFrame(afectados)
        st.dataframe(df_af, use_container_width=True, hide_index=True)


def _tab_reglas_activas() -> None:
    """Tab 1: Reglas Activas — tabla, crear, editar."""
    rules = _load_rules()
    if rules is None:
        st.warning("Error de conexión con la API")
        return

    # ── Nueva regla ────────────────────────────────────────────────────
    if st.button("+ Nueva Regla", type="primary"):
        with st.expander("Crear nueva regla", expanded=True):
            _form_nueva_regla()

    st.divider()

    # ── Tabla de reglas ────────────────────────────────────────────────
    selected_id = _reglas_table(rules)

    if selected_id:
        _render_regla_editor(selected_id)


def _form_nueva_regla() -> None:
    """Formulario para crear una nueva regla."""
    col_n1, col_n2, col_n3 = st.columns(3)
    with col_n1:
        regla_id = st.text_input("ID de la regla", key="new_regla_id", placeholder="R8-NUEVA")
    with col_n2:
        nombre = st.text_input("Nombre", key="new_nombre", placeholder="Nueva regla")
    with col_n3:
        tipo_regla = st.selectbox("Tipo", ["RECHAZAR", "APROBAR", "ESCALAR_FORZOSO"], key="new_tipo")

    prioridad = st.number_input("Prioridad", min_value=0, max_value=100, value=10, key="new_prioridad")
    descripcion = st.text_area("Descripción", key="new_descripcion", placeholder="Qué detecta esta regla")

    match_type = st.selectbox("Match", ["all", "any"], key="new_match")

    st.subheader("Condiciones")
    condiciones = _render_condition_builder("new_rule")

    users = _load_users()
    user_options = {u["nombre"]: u["nombre"] for u in users} if users else {}
    if not user_options:
        user_options = {"fraude_admin": "fraude_admin"}

    created_by = st.selectbox("Creado por", list(user_options.keys()), key="new_created_by")

    cambio_desc = st.text_area(
        "Motivo de creación",
        key="new_motivo",
        placeholder="Ej: Nueva regla para detectar...",
    )

    if st.button("Crear regla", key="btn_crear_regla"):
        if not regla_id or not nombre or not condiciones:
            st.warning("Completa todos los campos obligatorios (ID, nombre, al menos una condición)")
            return

        payload = {
            "regla_id": regla_id,
            "nombre": nombre,
            "tipo_regla": tipo_regla,
            "prioridad": prioridad,
            "config": {
                "descripcion": descripcion,
                "match": match_type,
                "condiciones": condiciones,
            },
            "updated_by": created_by,
            "cambio_descripcion": cambio_desc or "Creación de la regla",
        }

        result = post("/rules", json=payload)
        if result:
            st.success(f"Regla {regla_id} creada exitosamente")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error("Error al crear la regla")


def _tab_simular() -> None:
    """Tab 2: Simular Cambio — evaluar impacto sin persistir."""
    st.subheader("Simular impacto de un cambio")

    rules = _load_rules()
    if rules is None:
        st.warning("Error de conexión con la API")
        return

    reglas_opciones = ["Nueva regla — solo simular"] + [r["regla_id"] for r in rules]
    accion_seleccion = st.selectbox("Acción", ["update", "create", "delete"], key="sim_accion")
    regla_seleccionada = st.selectbox("Regla", reglas_opciones, key="sim_regla")

    if accion_seleccion == "delete":
        if regla_seleccionada == "Nueva regla — solo simular":
            st.warning("Selecciona una regla existente para simular eliminación")
            return
        if st.button("Simular eliminación", key="sim_delete_btn"):
            with st.spinner("Simulando..."):
                result = simulate_rules({
                    "accion": "delete",
                    "regla_id": regla_seleccionada,
                })
            if result:
                _mostrar_simulacion(result)
            else:
                st.error("Error en la simulación")
        return

    # Create / Update
    is_new = regla_seleccionada == "Nueva regla — solo simular"
    tipo_regla = st.selectbox("Tipo", ["RECHAZAR", "APROBAR", "ESCALAR_FORZOSO"], key="sim_tipo")
    match_type = st.selectbox("Match", ["all", "any"], key="sim_match")
    descripcion = st.text_area("Descripción", key="sim_descripcion")

    st.subheader("Condiciones")
    condiciones = _render_condition_builder("sim_builder")

    if st.button("Ejecutar simulación", key="sim_run_btn"):
        payload: dict = {
            "accion": accion_seleccion,
            "regla_id": regla_seleccionada if not is_new else "SIM-NUEVA",
            "config": {
                "descripcion": descripcion,
                "match": match_type,
                "condiciones": condiciones,
            },
            "tipo_regla": tipo_regla,
        }
        with st.spinner("Simulando..."):
            result = simulate_rules(payload)
        if result:
            _mostrar_simulacion(result)
        else:
            st.error("Error en la simulación")


def _tab_historial() -> None:
    """Tab 3: Historial de versiones de una regla."""
    import pandas as pd

    st.subheader("Historial de versiones")

    rules = _load_rules()
    if rules is None:
        st.warning("Error de conexión con la API")
        return

    regla_opciones = [r["regla_id"] for r in rules]
    if not regla_opciones:
        st.info("No hay reglas para consultar historial")
        return

    regla_seleccionada = st.selectbox("Seleccionar regla", regla_opciones, key="hist_regla")

    if st.button("Ver historial", key="hist_ver_btn"):
        versions = get_rule_versions(regla_seleccionada)
        if versions is None:
            st.error("Error al cargar el historial")
            return

        if not versions:
            st.info("Sin versiones registradas")
            return

        df_vers = pd.DataFrame(versions)
        cols = ["version_id", "version", "cambio_descripcion", "updated_by", "updated_at"]
        df_display = df_vers[cols].copy()
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        for idx, row in df_vers.iterrows():
            with st.expander(f"Versión {row.get('version', '?')} — {row.get('cambio_descripcion', 'sin descripción')}"):
                st.json(row.get("config", {}))


def render_rules() -> None:
    """Renderiza la página de Reglas de Decisión con 3 tabs."""
    st.title("Reglas de Decisión")

    tab1, tab2, tab3 = st.tabs(["Reglas Activas", "Simular Cambio", "Historial"])

    with tab1:
        _tab_reglas_activas()

    with tab2:
        _tab_simular()

    with tab3:
        _tab_historial()
render_rules()
