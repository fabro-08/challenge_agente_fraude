"""Nodo final_decision: combina reglas + LLM para la decisión final.

Usa una jerarquía determinista (no score continuo). La confianza se elimina;
la decisión se basa en qué regla disparó y el veredicto del LLM.

Precedencia:
1. Si RuleEngine dijo RECHAZAR → RECHAZAR
2. Si RuleEngine dijo APROBAR → APROBAR
3. Si hay palabras críticas → ESCALAR (seguridad de marca)
4. LLM decide en ambiguos vía veredicto:
   - veredicto empieza con "APROBAR" → APROBAR
   - veredicto empieza con "RECHAZAR" → RECHAZAR
   - veredicto empieza con "ESCALAR" o vacío → ESCALAR
"""

from src.pipeline.state import CaseState


def final_decision(state: CaseState) -> CaseState:
    """Emite la decisión final combinando reglas y LLM.

    Args:
        state: Estado con ``rule_result``, ``llm_analysis``, ``rule_signals``,
            ``rule_disparada`` (nombre de la regla que disparó).

    Returns:
        Estado actualizado con ``final_decision``, ``justification``, ``signals``.
    """
    rule_result = state.get("rule_result")
    rule_signals = state.get("rule_signals", [])
    rule_disparada = state.get("rule_disparada", "")
    llm = state.get("llm_analysis") or {}
    llm_signals = llm.get("señales", [])
    veredicto = (llm.get("veredicto") or "").strip()
    llm_just = llm.get("justificacion", "")

    todas_senales = list(rule_signals) + llm_signals

    # 1. RECHAZAR por reglas
    if rule_result == "RECHAZAR":
        state["final_decision"] = "RECHAZAR"
        state["justification"] = (
            f"RECHAZAR por señales de fraude detectadas por reglas: "
            f"{'; '.join(rule_signals)}."
        )
        state["signals"] = todas_senales
        return state

    # 2. APROBAR por reglas
    if rule_result == "APROBAR":
        state["final_decision"] = "APROBAR"
        state["justification"] = (
            f"APROBAR: caso consistente con perfil legítimo. "
            f"Señales: {'; '.join(rule_signals)}."
        )
        state["signals"] = todas_senales
        return state

    # 3. Palabras críticas → siempre ESCALAR
    if any("palabras_criticas" in s or "seguridad de marca" in s for s in rule_signals):
        state["final_decision"] = "ESCALAR"
        state["justification"] = (
            "ESCALAR por seguridad de marca: el reclamo contiene "
            "palabras críticas que requieren revisión humana."
        )
        state["signals"] = todas_senales
        return state

    # 4. LLM decide en ambiguos vía veredicto
    veredicto_upper = veredicto.upper()
    if veredicto_upper.startswith("RECHAZAR"):
        state["final_decision"] = "RECHAZAR"
        state["justification"] = f"RECHAZAR por análisis LLM: {llm_just}"
    elif veredicto_upper.startswith("APROBAR"):
        state["final_decision"] = "APROBAR"
        state["justification"] = f"APROBAR por análisis LLM: {llm_just}"
    else:
        state["final_decision"] = "ESCALAR"
        state["justification"] = (
            f"ESCALAR: caso ambiguo. LLM: {veredicto or llm_just}"
        )

    state["signals"] = todas_senales
    return state
