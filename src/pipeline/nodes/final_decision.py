"""Nodo final_decision: combina reglas + LLM para la decisión final.

Usa una jerarquía determinista (no score continuo). Tres vías:

1. APROBAR/RECHAZAR por reglas → decisión fija, sin LLM.
   - ``justificacion_regla`` = un bloque por regla disparada
     (``R1 — <descripcion>`` + ``<explicacion>`` en la línea siguiente).
   - ``senales_regla`` = ``campo operador umbral = valor_real``.
2. ESCALAR forzoso (palabras críticas) → decisión FORZADA a ESCALAR; el LLM
   participa solo para aportar análisis (``justificacion_llm``/``senales_llm``).
3. AMBIGUO → decide el LLM vía veredicto (``decision_llm``); la justificación
   y las señales las genera el LLM.

``justification`` (estado) es la justificación principal derivada para la API
(``justificacion_llm`` si el LLM participó, si no ``justificacion_regla``).
"""

from src.pipeline.state import CaseState

PREFIJOS = ("APROBAR", "RECHAZAR", "ESCALAR")

_TIPO_POR_DECISION = {
    "APROBAR": "APROBAR",
    "RECHAZAR": "RECHAZAR",
    "ESCALAR": "ESCALAR_FORZOSO",
}


def _sin_prefijo(texto: str) -> str:
    """Quita el prefijo "APROBAR:" / "RECHAZAR:" / "ESCALAR:" de un texto."""
    t = (texto or "").strip()
    for p in PREFIJOS:
        if t.upper().startswith(p + ":"):
            return t[len(p) + 1:].strip()
    return t


def _justificacion_reglas(rule_details: list[dict], decision: str) -> str:
    """Justificación de reglas: un bloque por regla disparada.

    Cada bloque tiene dos líneas (separadas por ``\\n``):
        ``regla_id — descripcion``
        ``explicacion``  (texto preseteado; se omite si la regla no lo tiene)

    Los bloques se unen con ``\\n\\n`` para respetar el salto de línea al
    renderizarse (UI, API, Excel).

    Args:
        rule_details: Checklist por regla con ``regla_id``, ``descripcion``,
            ``explicacion``, ``tipo_regla`` y ``se_disparo``.
        decision: Decisión que resuelve (APROBAR/RECHAZAR/ESCALAR).

    Returns:
        Texto con las reglas que dispararon la decisión, una por bloque.
    """
    tipo = _TIPO_POR_DECISION.get(decision)
    disparadas = [
        r for r in (rule_details or [])
        if r.get("se_disparo") and r.get("tipo_regla") == tipo
    ]
    if not disparadas:
        disparadas = [r for r in (rule_details or []) if r.get("se_disparo")]
    if not disparadas:
        return ""

    bloques = []
    for r in disparadas:
        desc = r.get("descripcion") or r.get("nombre", "")
        cabecera = f"{r.get('regla_id', '?')} — {desc}" if desc else r.get("regla_id", "?")
        explicacion = (r.get("explicacion") or "").strip()
        bloques.append(f"{cabecera}\n{explicacion}" if explicacion else cabecera)
    return "\n\n".join(bloques)


def _llm_justificacion(llm: dict) -> str | None:
    """Justificación del LLM, sin prefijo de decisión (o None si no aplica)."""
    if not llm:
        return None
    veredicto = (llm.get("veredicto") or "").strip()
    just = _sin_prefijo(llm.get("justificacion", "")) or _sin_prefijo(veredicto)
    return just or None


def _llm_senales(llm: dict) -> list[str]:
    """Señales canónicas generadas por el LLM (snake_case)."""
    if not llm:
        return []
    return [
        s.get("señal", "") for s in llm.get("señales_explicadas", [])
        if isinstance(s, dict) and s.get("señal")
    ]


def final_decision(state: CaseState) -> CaseState:
    """Emite la decisión final combinando reglas y LLM.

    Args:
        state: Estado con ``rule_result``, ``decision_regla``,
            ``decision_llm``, ``senales_regla`` y ``llm_analysis``.

    Returns:
        Estado actualizado con ``final_decision``, ``justificacion_regla``,
        ``justificacion_llm``, ``senales_regla`` y ``senales_llm``.
    """
    rule_result = state.get("rule_result")
    decision_regla = state.get("decision_regla", "AMBIGUO")
    senales_regla = [s for s in state.get("senales_regla", []) if s and s.strip()]
    llm = state.get("llm_analysis") or {}

    # 1. APROBAR / RECHAZAR por reglas (sin LLM)
    if rule_result in ("APROBAR", "RECHAZAR"):
        state["final_decision"] = rule_result
        state["decision_regla"] = decision_regla
        state["decision_llm"] = None
        state["justificacion_regla"] = (
            state.get("justificacion_regla")
            or _justificacion_reglas(state.get("rule_details", []), rule_result)
        )
        state["justificacion_llm"] = None
        state["senales_regla"] = senales_regla
        state["senales_llm"] = []
        state["justification"] = state["justificacion_regla"]
        return state

    # 2. ESCALAR forzoso (palabras críticas): decisión forzada a ESCALAR;
    #    el LLM aporta justificación y señales enriquecidas.
    if rule_result == "ESCALAR":
        state["final_decision"] = "ESCALAR"
        state["decision_regla"] = "ESCALAR"
        state["justificacion_regla"] = (
            state.get("justificacion_regla")
            or _justificacion_reglas(state.get("rule_details", []), "ESCALAR")
        )
        state["justificacion_llm"] = _llm_justificacion(llm)
        state["senales_regla"] = senales_regla
        state["senales_llm"] = _llm_senales(llm)
        state["justification"] = (
            state["justificacion_llm"] or state["justificacion_regla"]
        )
        return state

    # 3. AMBIGUO → decide el LLM vía veredicto
    decision_llm = state.get("decision_llm") or "ESCALAR"
    state["decision_llm"] = decision_llm
    state["final_decision"] = decision_llm
    state["justificacion_regla"] = ""
    state["justificacion_llm"] = _llm_justificacion(llm)
    state["senales_regla"] = []
    state["senales_llm"] = _llm_senales(llm)
    state["justification"] = state["justificacion_llm"] or (
        "Revisión manual requerida por ambigüedad en la evidencia."
    )

    # decision_regla ya fue seteado por apply_rules; se asegura por defecto.
    state["decision_regla"] = decision_regla
    return state
