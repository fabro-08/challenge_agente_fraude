"""Simulador de impacto de cambios de reglas (efímero: nunca persiste).

Cuando el equipo de fraude propone un cambio (nuevo threshold, regla desactivada,
regla nueva), el simulador re-evalúa la capa de reglas sobre los casos almacenados
y compara contra la configuración actual. Devuelve cuántos casos cambiarían de
decisión y cuáles, sin escribir nada en la base de datos.

Limitación intencional: la simulación solo cubre la capa de reglas (milisegundos).
Los casos ambiguos se reportan como "LLM/ESCALAR" usando su decisión almacenada
como referencia — el LLM no se re-ejecuta durante la simulación.
"""

from collections.abc import Callable
from copy import deepcopy
from typing import Any

import psycopg2

from src.rules.generic_engine import CaseEvaluation, GenericRuleEngine, RuleDefinition
from src.rules.repository import DB_CONFIG, cargar_reglas_activas


def _cargar_casos(filtros: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Carga casos con todas sus columnas para simulación.

    Args:
        filtros: Filtros opcionales. Soportados: ``es_sintetico`` (bool),
            ``limite`` (int).

    Returns:
        Lista de dicts con las columnas de ``cases`` + ``features`` y la
        decisión almacenada como ``recomendacion_agente``.
    """
    filtros = filtros or {}
    where = []
    params: list[Any] = []

    if "es_sintetico" in filtros:
        where.append("c.es_sintetico = %s")
        params.append(filtros["es_sintetico"])

    sql = (
        "SELECT c.*, f.*, a.decision AS recomendacion_agente "
        "FROM cases c "
        "LEFT JOIN features f ON f.caso_id = c.caso_id "
        "LEFT JOIN resolution_case a ON a.caso_id = c.caso_id"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY c.caso_id"
    if "limite" in filtros:
        sql += " LIMIT %s"
        params.append(int(filtros["limite"]))

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columnas = [d[0] for d in cur.description]
            return [dict(zip(columnas, r)) for r in cur.fetchall()]
    finally:
        conn.close()


def _etiqueta_decision(evaluacion: CaseEvaluation, decision_almacenada: str | None) -> str:
    """Etiqueta comparable de decisión para la matriz de transiciones.

    Los casos ambiguos no tienen decisión de reglas; se agrupan como
    ``LLM/ESCALAR`` porque el pipeline los derivaría al LLM.
    """
    if evaluacion.decision == "AMBIGUO":
        return "LLM/ESCALAR"
    return evaluacion.decision


def simular_cambio(
    mutador: Callable[[list[RuleDefinition]], list[RuleDefinition]],
    filtros: dict[str, Any] | None = None,
    max_afectados: int = 50,
) -> dict[str, Any]:
    """Simula el impacto de una modificación al conjunto de reglas.

    Args:
        mutador: Función que recibe la lista actual de RuleDefinition y devuelve
            la lista propuesta (modificada, con regla nueva, sin una regla, etc.).
        filtros: Filtros de casos a evaluar (``es_sintetico``, ``limite``).
        max_afectados: Máximo de caso_ids a incluir en la respuesta.

    Returns:
        Dict con ``casos_evaluados``, ``cambian_decision``, ``transiciones``
        (dict "ANTES→DESPUÉS": n) y ``casos_afectados`` (lista de detalles).
        No escribe nada en la base de datos.
    """
    reglas_actuales = cargar_reglas_activas()
    # deepcopy: el mutador recibe objetos independientes; sin esto, mutar una
    # RuleDefinition también alteraría la config del engine "actual".
    reglas_propuestas = mutador(deepcopy(reglas_actuales))

    engine_actual = GenericRuleEngine(reglas_actuales)
    engine_propuesto = GenericRuleEngine(reglas_propuestas)

    casos = _cargar_casos(filtros)

    transiciones: dict[str, int] = {}
    afectados: list[dict[str, Any]] = []

    for caso in casos:
        ev_actual = engine_actual.evaluate_case(caso)
        ev_propuesto = engine_propuesto.evaluate_case(caso)

        antes = _etiqueta_decision(ev_actual, caso.get("recomendacion_agente"))
        despues = _etiqueta_decision(ev_propuesto, caso.get("recomendacion_agente"))

        if antes != despues:
            clave = f"{antes}→{despues}"
            transiciones[clave] = transiciones.get(clave, 0) + 1
            if len(afectados) < max_afectados:
                afectados.append(
                    {
                        "caso_id": caso["caso_id"],
                        "decision_almacenada": caso.get("recomendacion_agente"),
                        "antes_reglas": antes,
                        "despues_reglas": despues,
                        "senales_nuevas": ev_propuesto.signals,
                    }
                )

    return {
        "casos_evaluados": len(casos),
        "cambian_decision": sum(transiciones.values()),
        "transiciones": dict(sorted(transiciones.items(), key=lambda kv: -kv[1])),
        "casos_afectados": afectados,
        "nota": (
            "Simulación de capa de reglas únicamente. Casos LLM/ESCALAR usan la "
            "decisión almacenada como referencia; el LLM no se re-ejecuta."
        ),
    }
