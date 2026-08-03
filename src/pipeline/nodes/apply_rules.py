"""Nodo apply_rules: evalúa el caso contra las reglas (thresholds.yaml).

Las reglas se cargan de ``src/rules/thresholds.yaml`` vía ``RuleEngine`` y se
aplican en orden de precedencia (ESCALAR forzoso → RECHAZAR → APROBAR → ESCALAR
por ambigüedad). El resultado queda en ``rule_result``/``decision_regla`` para
el routing del grafo y en ``senales_regla``/``justificacion_regla`` para el
output. No depende de reglas en la base de datos.

El routing del grafo (``graph.py``) usa ``rule_result``:
- APROBAR / RECHAZAR → resuelven sin LLM.
- ESCALAR (forzoso) y AMBIGUO → pasan al nodo LLM.
"""

import logging

import pandas as pd

from src.pipeline.state import CaseState
from src.rules.rule_engine import RuleEngine

logger = logging.getLogger(__name__)


def apply_rules(state: CaseState) -> CaseState:
    """Aplica las reglas del YAML al caso.

    Args:
        state: Estado con ``features``.

    Returns:
        Estado actualizado con ``rule_result``, ``decision_regla``,
        ``senales_regla``, ``justificacion_regla`` y ``rule_details``.
    """
    features = state["features"]
    engine = RuleEngine()
    df = pd.DataFrame([features])
    row = engine.decide(df).iloc[0]

    decision = row["recomendacion"]
    senales = [s for s in str(row["senales_usadas"]).split(" | ") if s]

    state["justificacion_regla"] = row["justificacion"]
    state["rule_details"] = []
    state["rule_disparada"] = ""
    state["senales_regla"] = [s for s in senales if "ambiguo" not in s.lower()]

    if decision == "ESCALAR" and any("ambiguo" in s.lower() for s in senales):
        # Caso ambiguo: lo resuelve el LLM.
        state["decision_regla"] = "AMBIGUO"
        state["rule_result"] = None
        state["senales_regla"] = []
    elif decision == "ESCALAR":
        # ESCALAR forzoso (palabras críticas de marca).
        state["decision_regla"] = "ESCALAR"
        state["rule_result"] = "ESCALAR"
    else:
        state["decision_regla"] = decision
        state["rule_result"] = decision

    return state
