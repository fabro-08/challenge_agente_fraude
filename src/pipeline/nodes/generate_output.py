"""Nodo generate_output: formatea la respuesta final y consolida el checklist."""

import logging

from src.pipeline.state import CaseState
from src.rules import repository

logger = logging.getLogger(__name__)


def _dedup(lista: list[str]) -> list[str]:
    """Elimina vacíos y duplicados preservando el orden."""
    return list(dict.fromkeys(s for s in lista if s and s.strip()))


def _truncar(texto: str, max_len: int = 500) -> str:
    if texto and len(texto) > max_len:
        return texto[: max_len - 3] + "..."
    return texto


def generate_output(state: CaseState) -> CaseState:
    """Formatea el output final del pipeline y consolida ``reglas_checklist``.

    Args:
        state: Estado con ``final_decision``, ``justificacion_regla``,
            ``justificacion_llm``, ``senales_regla``, ``senales_llm``
            y ``rule_details``.

    Returns:
        Estado con campos finales listos para persistir o retornar.
    """
    # Señales deduplicadas (regla y LLM por separado)
    state["senales_regla"] = _dedup(state.get("senales_regla", []))
    state["senales_llm"] = _dedup(state.get("senales_llm", []))

    # Asegurar los resultados discretos para persistencia en resolution_case.
    state["decision_regla"] = state.get("decision_regla", "AMBIGUO")
    state["decision_llm"] = state.get("decision_llm")

    # Asegurar que las justificaciones no sean excesivamente largas.
    # justificacion_regla es multilínea (bloque por regla con su explicación),
    # por eso tolera un poco más de longitud que el resto.
    state["justificacion_regla"] = _truncar(state.get("justificacion_regla", ""), 1200)
    if state.get("justificacion_llm"):
        state["justificacion_llm"] = _truncar(state["justificacion_llm"])
    state["justification"] = _truncar(state.get("justification", ""))

    # Pasar llm_resultado al estado final (lo persiste services.py)
    if not state.get("llm_resultado"):
        state["llm_resultado"] = None

    # Consolidar el checklist por regla (anclado a la versión que procesó el caso)
    # en el estado; lo persiste services.py en resolution_case.reglas_checklist.
    rule_details = state.get("rule_details") or []
    if rule_details:
        try:
            state["reglas_checklist"] = repository.enriquecer_checklist(rule_details)
        except Exception as e:  # la decisión ya está en el estado
            logger.warning(
                "No se pudo enriquecer reglas_checklist para %s: %s",
                state["case_id"],
                e,
            )
            state["reglas_checklist"] = [
                dict(r, version=0) for r in rule_details
            ]
    else:
        state["reglas_checklist"] = []

    return state
