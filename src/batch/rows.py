"""Construcción de filas planas del entregable a partir de un estado del grafo.

Compartido entre el worker batch (modo demo ``persistir=False``) y la API
(export), para tener una única fuente de verdad del formato de fila.
"""

import json
from typing import Any


def resumen_llm(llm_resultado: Any) -> str:
    """Extrae el resumen legible del JSONB del LLM (o '' si no aplica)."""
    if not llm_resultado:
        return ""
    try:
        data = llm_resultado if isinstance(llm_resultado, dict) else json.loads(llm_resultado)
    except (TypeError, json.JSONDecodeError):
        return str(llm_resultado)
    veredicto = data.get("veredicto", "")
    resumen = data.get("resumen", "")
    return " | ".join(p for p in (veredicto, resumen) if p)


def fila_export_desde_estado(resultado: dict[str, Any]) -> dict[str, Any]:
    """Construye una fila del entregable a partir del estado del grafo.

    Usada por el batch en modo demo (``persistir=False``) para poder generar
    el Excel sin escribir en ``resolution_case``.
    """
    raw = resultado.get("raw_data") or {}
    feats = resultado.get("features") or {}
    decision_regla = resultado.get("decision_regla", "AMBIGUO")
    llm_resultado = resultado.get("llm_resultado")
    fuente = "reglas" if decision_regla == "ESCALAR" else ("llm" if llm_resultado else "reglas")

    return {
        "caso_id": raw.get("caso_id"),
        "usuario_id": raw.get("usuario_id"),
        "antiguedad_usuario_dias": raw.get("antiguedad_usuario_dias"),
        "ciudad": raw.get("ciudad"),
        "vertical": raw.get("vertical"),
        "restaurante": raw.get("restaurante"),
        "valor_orden_mxn": raw.get("valor_orden_mxn"),
        "compensacion_solicitada_mxn": raw.get("compensacion_solicitada_mxn"),
        "num_compensaciones_90d": raw.get("num_compensaciones_90d"),
        "monto_compensado_90d_mxn": raw.get("monto_compensado_90d_mxn"),
        "entrega_confirmada_gps": raw.get("entrega_confirmada_gps"),
        "tiempo_entrega_real_min": raw.get("tiempo_entrega_real_min"),
        "flags_fraude_previos": raw.get("flags_fraude_previos"),
        "motivo_reclamo": raw.get("motivo_reclamo"),
        "descripcion_reclamo": raw.get("descripcion_reclamo"),
        "comp_ratio": feats.get("comp_ratio"),
        "freq_densidad": feats.get("freq_densidad"),
        "score_riesgo_previo": feats.get("score_riesgo_previo"),
        "fuente": fuente,
        "recomendacion": resultado.get("final_decision"),
        "decision_regla": decision_regla,
        "decision_llm": resultado.get("decision_llm"),
        "justificacion_llm": resultado.get("justificacion_llm"),
        "justificacion_regla": resultado.get("justificacion_regla"),
        "senales_llm": " | ".join(resultado.get("senales_llm") or []),
        "senales_regla": " | ".join(resultado.get("senales_regla") or []),
        "resumen_llm": resumen_llm(llm_resultado),
        "fallback": " | ".join(resultado.get("fallback_info") or []),
    }