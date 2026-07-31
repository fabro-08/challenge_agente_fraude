"""Nodo generate_output: formatea la respuesta final y persiste el checklist de reglas."""

import logging

import psycopg2

from src.pipeline.state import CaseState
from src.rules import repository

logger = logging.getLogger(__name__)


def generate_output(state: CaseState) -> CaseState:
    """Formatea el output final del pipeline y persiste ``resultados_reglas``.

    Args:
        state: Estado con ``final_decision``, ``justification``, ``signals``
            y ``rule_details``.

    Returns:
        Estado con campos finales listos para persistir o retornar.
    """
    # Asegurar que signals no tenga duplicados ni vacíos
    signals = [s for s in state.get("signals", []) if s and s.strip()]
    state["signals"] = list(dict.fromkeys(signals))  # deduplicar preservando orden

    # Asegurar que justification no sea excesivamente larga
    just = state.get("justification", "")
    if len(just) > 500:
        state["justification"] = just[:497] + "..."

    # Pasar llm_resultado al estado final (lo persiste services.py)
    if not state.get("llm_resultado"):
        state["llm_resultado"] = None

    # Persistir checklist de reglas (anclado a la versión que procesó el caso).
    # Tolerante a fallos: la decisión ya está en el estado; un error de
    # persistencia no debe romper el pipeline.
    rule_details = state.get("rule_details") or []
    if rule_details:
        try:
            n = repository.persistir_resultados(state["case_id"], rule_details)
            logger.debug("resultados_reglas: %s filas persistidas para %s", n, state["case_id"])
        except psycopg2.Error as e:
            logger.warning("No se pudo persistir resultados_reglas para %s: %s", state["case_id"], e)

    return state
