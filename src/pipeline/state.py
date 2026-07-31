"""Estado compartido entre nodos del pipeline LangGraph."""

from typing import Any, TypedDict


class CaseState(TypedDict, total=False):
    """Estado que fluye entre los nodos del grafo.

    Attributes:
        case_id: Identificador único del caso.
        raw_data: Datos crudos del caso (de PostgreSQL o entrada directa).
        features: Features calculadas por FeatureEngineer.
        rule_result: Resultado de RuleEngine (APROBAR / RECHAZAR / None si ambiguo).
        rule_signals: Señales que disparó RuleEngine.
        rule_details: Checklist completo por regla (version_id, se_disparo, detalle)
            para persistir en ``resultados_reglas`` y mostrar en la UI.
        llm_analysis: Resultado crudo del LLM — dict con justificacion, resumen,
            veredicto y señales_explicadas. None si no se ejecutó (caso resuelto por reglas).
        llm_resultado: Estructura legible para el agente CS: resumen, veredicto
            y señales_explicadas con peso. None si no se ejecutó LLM.
        llm_analysis: Análisis del LLM sobre descripcion_reclamo (None si no aplica).
        final_decision: Decisión final (APROBAR / RECHAZAR / ESCALAR).
        justification: Justificación legible para humanos.
        signals: Todas las señales usadas en la decisión.
        es_sintetico: Si el caso es sintético.
    """

    case_id: str
    raw_data: dict[str, Any]
    features: dict[str, Any]
    rule_result: str | None
    rule_signals: list[str]
    rule_details: list[dict[str, Any]]
    llm_analysis: dict[str, Any] | None
    llm_resultado: dict[str, Any] | None
    final_decision: str
    justification: str
    signals: list[str]
    es_sintetico: bool
