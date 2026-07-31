"""Nodo apply_rules: evalúa el caso contra las reglas activas.

Fuente de reglas:
1. Si la DB tiene reglas configuradas (``configuracion_reglas``) →
   ``GenericRuleEngine`` (motor declarativo gestionado por fraude, step 06b).
2. Si la tabla está vacía o la DB no responde → fallback a ``RuleEngine``
   (YAML hardcodeado, step 03) para no dejar el pipeline inoperativo.

El checklist completo (``rule_details``) viaja en el estado y lo persiste
``generate_output`` en la tabla ``resultados_reglas``.
"""

import logging

import pandas as pd
import psycopg2

from src.pipeline.state import CaseState
from src.rules import repository
from src.rules.generic_engine import GenericRuleEngine
from src.rules.rule_engine import RuleEngine

logger = logging.getLogger(__name__)


def _aplicar_generico(state: CaseState) -> CaseState:
    """Evalúa con el motor genérico (reglas versionadas en DB)."""
    features = state["features"]
    engine = GenericRuleEngine(repository.cargar_reglas_activas())
    evaluacion = engine.evaluate_case(features)

    state["rule_details"] = [
        {
            "regla_id": r.regla_id,
            "version_id": r.version_id,
            "nombre": r.nombre,
            "tipo_regla": r.tipo_regla,
            "se_disparo": r.se_disparo,
            "valor_actual": r.valor_actual,
            "detalle": r.detalle,
        }
        for r in evaluacion.rule_results
    ]

    if evaluacion.decision in ("APROBAR", "RECHAZAR"):
        state["rule_result"] = evaluacion.decision
        # La primera regla que disparó (por prioridad dentro del tipo)
        for r in evaluacion.rule_results:
            if r.se_disparo and r.tipo_regla == evaluacion.decision:
                state["rule_disparada"] = f"{r.regla_id}: {r.nombre}"
                break
    else:
        # ESCALAR forzoso o AMBIGUO: lo resuelve final_decision / llm_classify
        state["rule_result"] = None
        state["rule_disparada"] = ""
    state["rule_signals"] = evaluacion.signals
    return state


def _aplicar_fallback_yaml(state: CaseState) -> CaseState:
    """Evalúa con el motor original (thresholds.yaml) sin persistencia de checklist."""
    logger.warning("apply_rules: usando fallback YAML (DB sin reglas o no disponible)")
    engine = RuleEngine()
    df = pd.DataFrame([state["features"]])
    row = engine.decide(df).iloc[0]

    decision = row["recomendacion"]
    state["rule_result"] = decision if decision in ("APROBAR", "RECHAZAR") else None
    state["rule_signals"] = row["senales_usadas"].split(" | ")
    state["rule_details"] = []
    state["rule_disparada"] = ""
    return state


def apply_rules(state: CaseState) -> CaseState:
    """Aplica las reglas activas al caso.

    Args:
        state: Estado con ``features``.

    Returns:
        Estado actualizado con ``rule_result``, ``rule_signals`` y ``rule_details``.
    """
    try:
        if not repository.tablas_reglas_vacias():
            return _aplicar_generico(state)
    except psycopg2.OperationalError:
        pass  # DB no disponible → fallback

    return _aplicar_fallback_yaml(state)
