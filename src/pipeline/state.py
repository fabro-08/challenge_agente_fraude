"""Estado compartido entre nodos del pipeline LangGraph."""

from typing import Any, TypedDict


class CaseState(TypedDict, total=False):
    """Estado que fluye entre los nodos del grafo.

    Attributes:
        case_id: Identificador único del caso.
        raw_data: Datos crudos del caso (de PostgreSQL o entrada directa).
        features: Features calculadas por FeatureEngineer (raw + features).
        features_version: Versión del feature set usada (``features.version``).
        rule_result: Resultado del motor de reglas para el routing del grafo:
            APROBAR / RECHAZAR resuelven sin LLM; ESCALAR (forzoso) y None
            (ambiguo) pasan al nodo LLM.
        decision_regla: Resultado crudo del motor de reglas
            (APROBAR / RECHAZAR / AMBIGUO / ESCALAR).
        decision_llm: Veredicto discreto del LLM
            (APROBAR / RECHAZAR / ESCALAR). None si no se ejecutó LLM.
        rule_details: Checklist completo por regla (regla_id, version_id,
            nombre, tipo_regla, se_disparo, descripcion, explicacion,
            condiciones, valor_actual, detalle).
        reglas_checklist: Checklist enriquecido (con ``version``) para
            persistir en ``resolution_case.reglas_checklist`` (JSONB).
        justificacion_regla: Un bloque por regla disparada: ``R1 — <descripcion>``
            y la ``<explicacion>`` (texto preseteado) en la línea siguiente;
            los bloques se separan con ``\\n\\n``. Vacío si no aplica.
        justificacion_llm: Justificación generada por el LLM. None si el LLM
            no participó.
        senales_regla: Señales de las reglas disparadas en formato
            ``campo operador umbral = valor_real`` (ej. ``flags >= 2 = 3``).
        senales_llm: Señales canónicas (snake_case) generadas por el LLM.
        llm_analysis: Resultado crudo del LLM — dict con justificacion, resumen,
            veredicto y señales_explicadas. None si no se ejecutó (caso
            resuelto por reglas).
        llm_resultado: Estructura legible para el agente CS: resumen, veredicto
            y señales_explicadas con peso. None si no se ejecutó LLM.
        final_decision: Decisión final (APROBAR / RECHAZAR / ESCALAR).
            Para ESCALAR forzoso queda forzada a ESCALAR aunque el LLM
            participe aportando análisis.
        justification: Justificación principal legible (``justificacion_llm``
            si el LLM participó, si no ``justificacion_regla``).
        fallback_info: Motivos de degradación (reglas_yaml, reglas__irrecuperable,
            llm_circuit_open, llm_provider_error, llm_parsing, caso_timeout) para
            auditar por qué se degradó cada caso.
        es_sintetico: Si el caso es sintético.
    """

    case_id: str
    raw_data: dict[str, Any]
    features: dict[str, Any]
    features_version: str
    rule_result: str | None
    decision_regla: str | None
    decision_llm: str | None
    rule_details: list[dict[str, Any]]
    reglas_checklist: list[dict[str, Any]]
    justificacion_regla: str
    justificacion_llm: str | None
    senales_regla: list[str]
    senales_llm: list[str]
    llm_analysis: dict[str, Any] | None
    llm_resultado: dict[str, Any] | None
    final_decision: str
    justification: str
    fallback_info: list[str]
    es_sintetico: bool
