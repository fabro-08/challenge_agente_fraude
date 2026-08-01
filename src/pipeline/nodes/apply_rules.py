"""Nodo apply_rules: evalúa el caso contra las reglas activas.

Fuente de reglas:
1. Si la DB tiene reglas configuradas (``configuracion_reglas``) →
   ``GenericRuleEngine`` (motor declarativo gestionado por fraude, step 06b).
2. Si la tabla está vacía o la DB no responde → fallback a ``RuleEngine``
   (YAML hardcodeado, step 03) para no dejar el pipeline inoperativo.

El checklist completo (``rule_details``) viaja en el estado y lo consolida
``generate_output`` en ``resolution_case.reglas_checklist`` (JSONB). Además
deja ``senales_regla`` con el formato ``campo operador umbral = valor_real``
para las reglas que dispararon.
"""

import logging

import pandas as pd
import psycopg2

from src.pipeline.state import CaseState
from src.rules import repository
from src.rules.generic_engine import GenericRuleEngine
from src.rules.rule_engine import RuleEngine
from src.rules.signals import formato_senal_regla

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
            "descripcion": r.descripcion,
            "condiciones": [
                {
                    "campo": c.campo,
                    "operador": c.operador,
                    "valor_esperado": c.valor_esperado,
                    "valor_actual": c.valor_actual,
                    "se_cumple": c.se_cumple,
                }
                for c in r.condiciones
            ],
            "valor_actual": r.valor_actual,
            "detalle": r.detalle,
        }
        for r in evaluacion.rule_results
    ]

    # Resultado crudo del motor: APROBAR | RECHAZAR | AMBIGUO | ESCALAR.
    decision_motor = evaluacion.decision
    state["decision_regla"] = decision_motor

    # Señales "campo operador umbral = valor_real" de las reglas que dispararon.
    state["senales_regla"] = [
        s
        for r in state["rule_details"]
        if r["se_disparo"]
        for s in formato_senal_regla(r)
    ]

    if decision_motor == "ESCALAR":
        # ESCALAR forzoso: la decisión queda forzada a ESCALAR, pero el caso
        # igual pasa al LLM para generar el análisis enriquecido.
        state["rule_result"] = "ESCALAR"
        state["rule_disparada"] = "ESCALAR: seguridad de marca"
    elif decision_motor in ("APROBAR", "RECHAZAR"):
        state["rule_result"] = decision_motor
        # La primera regla que disparó (por prioridad dentro del tipo)
        for r in evaluacion.rule_results:
            if r.se_disparo and r.tipo_regla == decision_motor:
                state["rule_disparada"] = f"{r.regla_id}: {r.nombre}"
                break
    else:
        # AMBIGUO: lo resuelve el LLM.
        state["rule_result"] = None
        state["rule_disparada"] = ""
    return state


def _aplicar_fallback_yaml(state: CaseState) -> CaseState:
    """Evalúa con el motor original (thresholds.yaml) sin persistencia de checklist."""
    logger.warning("apply_rules: usando fallback YAML (DB sin reglas o no disponible)")
    engine = RuleEngine()
    df = pd.DataFrame([state["features"]])
    row = engine.decide(df).iloc[0]

    decision = row["recomendacion"]
    senales = row["senales_usadas"].split(" | ") if row["senales_usadas"] else []
    es_ambiguo = any("ambiguo" in s.lower() for s in senales)

    if decision == "ESCALAR" and es_ambiguo:
        state["decision_regla"] = "AMBIGUO"
        state["rule_result"] = None
        state["senales_regla"] = []
    elif decision == "ESCALAR":
        state["decision_regla"] = "ESCALAR"
        state["rule_result"] = "ESCALAR"
        state["senales_regla"] = [s for s in senales if s]
    else:
        state["decision_regla"] = decision
        state["rule_result"] = decision if decision in ("APROBAR", "RECHAZAR") else None
        state["senales_regla"] = [s for s in senales if s and "ambiguo" not in s.lower()]
    state["rule_details"] = []
    state["rule_disparada"] = ""
    return state


def apply_rules(state: CaseState) -> CaseState:
    """Aplica las reglas activas al caso.

    Args:
        state: Estado con ``features``.

    Returns:
        Estado actualizado con ``rule_result``, ``decision_regla``,
        ``senales_regla`` y ``rule_details``.
    """
    try:
        if not repository.tablas_reglas_vacias():
            return _aplicar_generico(state)
    except psycopg2.OperationalError:
        pass  # DB no disponible → fallback

    return _aplicar_fallback_yaml(state)
