"""Tests de la estructura de output del pipeline: decision_regla, decision_llm,
justificaciones separadas (regla/LLM) y señales por fuente (regla/LLM)."""

from src.pipeline.nodes.final_decision import final_decision
from src.pipeline.state import CaseState
from src.rules import signals


def _base_state(**kwargs) -> CaseState:
    state: CaseState = {
        "case_id": "COMP-TEST",
        "decision_regla": "AMBIGUO",
        "decision_llm": None,
        "senales_regla": [],
        "senales_llm": [],
        "rule_details": [],
    }
    state.update(kwargs)
    return state


def _regla(regla_id: str = "R1", tipo: str = "RECHAZAR",
           descripcion: str = "Usuario con 2 o más flags de fraude previos",
           explicacion: str = "El usuario tiene 2 o más flags de fraude previos: ya está señalado por el sistema.") -> dict:
    return {
        "regla_id": regla_id,
        "tipo_regla": tipo,
        "nombre": regla_id,
        "descripcion": descripcion,
        "explicacion": explicacion,
        "se_disparo": True,
        "condiciones": [
            {"campo": "flags_fraude_previos", "operador": ">=",
             "valor_esperado": 2, "valor_actual": 3}
        ],
    }


# ── final_decision ───────────────────────────────────────────────────────


def test_rechazar_por_reglas():
    st = final_decision(_base_state(
        rule_result="RECHAZAR", decision_regla="RECHAZAR",
        senales_regla=["flags_fraude_previos >= 2 = 3"],
        rule_details=[_regla()],
    ))
    assert st["final_decision"] == "RECHAZAR"
    assert st["decision_regla"] == "RECHAZAR"
    assert st["decision_llm"] is None
    assert st["senales_llm"] == []
    assert st["justificacion_regla"] == (
        "R1 — Usuario con 2 o más flags de fraude previos\n"
        "El usuario tiene 2 o más flags de fraude previos: ya está señalado por el sistema."
    )
    assert st["justification"] == st["justificacion_regla"]


def test_aprobar_por_reglas():
    st = final_decision(_base_state(
        rule_result="APROBAR", decision_regla="APROBAR",
        senales_regla=["gps_confirmada_usuario_antiguo"],
        rule_details=[_regla("A3", "APROBAR", "GPS confirmado, sin retraso, ratio normal, usuario antiguo",
                             explicacion="Entrega confirmada, sin demora, compensación que no excede la orden y usuario con historial.")],
    ))
    assert st["final_decision"] == "APROBAR"
    assert st["decision_llm"] is None
    assert st["justificacion_regla"] == (
        "A3 — GPS confirmado, sin retraso, ratio normal, usuario antiguo\n"
        "Entrega confirmada, sin demora, compensación que no excede la orden y usuario con historial."
    )


def test_justificacion_regla_multilineas_bloques():
    """Varias reglas disparadas → un bloque por regla, separados por doble salto."""
    st = final_decision(_base_state(
        rule_result="RECHAZAR", decision_regla="RECHAZAR",
        senales_regla=["flags_fraude_previos >= 2 = 3", "score_riesgo_previo > 10 = 14"],
        rule_details=[
            _regla(),
            _regla("R7", "RECHAZAR", "score_riesgo_previo (flags×2 + comps_90d×0.5) > p90",
                   explicacion="El score de riesgo previo supera el p90 del dataset: historial inaceptable."),
        ],
    ))
    esperado = (
        "R1 — Usuario con 2 o más flags de fraude previos\n"
        "El usuario tiene 2 o más flags de fraude previos: ya está señalado por el sistema.\n\n"
        "R7 — score_riesgo_previo (flags×2 + comps_90d×0.5) > p90\n"
        "El score de riesgo previo supera el p90 del dataset: historial inaceptable."
    )
    assert st["justificacion_regla"] == esperado


def test_justificacion_regla_sin_explicacion():
    """Si la regla no tiene explicacion (legacy), solo se muestra la cabecera."""
    st = final_decision(_base_state(
        rule_result="RECHAZAR", decision_regla="RECHAZAR",
        rule_details=[_regla(explicacion="")],
    ))
    assert st["justificacion_regla"] == "R1 — Usuario con 2 o más flags de fraude previos"


def test_escalar_forzado_con_llm():
    st = final_decision(_base_state(
        rule_result="ESCALAR", decision_regla="ESCALAR", decision_llm="ESCALAR",
        senales_regla=["descripcion_reclamo contains_any [alergi, intoxic] = alergi"],
        rule_details=[_regla("ESCALAR-1", "ESCALAR",
                             "Reclamo menciona alergia, intoxicación, policía, sangre, abogado, demanda")],
        llm_analysis={
            "veredicto": "ESCALAR: contiene palabras críticas que requieren revisión humana.",
            "justificacion": "El reclamo menciona términos de riesgo legal que requieren revisión humana.",
            "señales_explicadas": [
                {"señal": "palabras_criticas_seguridad", "explicacion": "menciona 'alergia'", "peso": "alto"}
            ],
        },
    ))
    assert st["final_decision"] == "ESCALAR"   # forzada por reglas
    assert st["decision_regla"] == "ESCALAR"
    assert st["decision_llm"] == "ESCALAR"
    assert st["justificacion_regla"].startswith("ESCALAR-1 —")
    assert st["justificacion_llm"] == "El reclamo menciona términos de riesgo legal que requieren revisión humana."
    assert st["senales_llm"] == ["palabras_criticas_seguridad"]
    assert st["justification"] == st["justificacion_llm"]


def test_escalar_forzado_aunque_llm_discrepe():
    """La decisión queda forzada a ESCALAR aunque el LLM emitiera otro veredicto."""
    st = final_decision(_base_state(
        rule_result="ESCALAR", decision_regla="ESCALAR", decision_llm="APROBAR",
        senales_regla=["descripcion_reclamo contains_any [alergi, intoxic] = alergi"],
        rule_details=[_regla("ESCALAR-1", "ESCALAR",
                             "Reclamo menciona alergia, intoxicación, policía, sangre, abogado, demanda")],
        llm_analysis={"veredicto": "APROBAR: reclamo legítimo",
                      "justificacion": "Reclamo legítimo.", "señales_explicadas": []},
    ))
    assert st["final_decision"] == "ESCALAR"
    assert st["decision_llm"] == "APROBAR"


def test_llm_decide_ambiguo():
    st = final_decision(_base_state(
        rule_result=None, decision_regla="AMBIGUO", decision_llm="APROBAR",
        llm_analysis={"veredicto": "APROBAR: reclamo legítimo",
                      "justificacion": "Usuario con 0 flags y 4+ años de antigüedad.",
                      "señales_explicadas": [
                          {"señal": "reclamo_subjetivo", "explicacion": "subjetivo", "peso": "medio"}
                      ]},
    ))
    assert st["final_decision"] == "APROBAR"
    assert st["decision_regla"] == "AMBIGUO"
    assert st["decision_llm"] == "APROBAR"
    assert st["senales_llm"] == ["reclamo_subjetivo"]
    assert st["justificacion_regla"] == ""


def test_justificacion_llm_sin_prefijo():
    st = final_decision(_base_state(
        rule_result=None, decision_regla="AMBIGUO", decision_llm="ESCALAR",
        llm_analysis={"veredicto": "ESCALAR: ambigüedad por GPS no confirmada requieren validación manual.",
                      "justificacion": "", "señales_explicadas": []},
    ))
    assert st["justificacion_llm"] == "ambigüedad por GPS no confirmada requieren validación manual."
    assert st["justification"] == st["justificacion_llm"]


# ── señales canónicas y formato ──────────────────────────────────────────


def test_senal_de_regla_mapeo():
    assert signals.senal_de_regla("R3") == "alta_frecuencia_reclamos"
    assert signals.senal_de_regla("ESCALAR-1") == "palabras_criticas_seguridad"
    assert signals.senal_de_regla("A3") == "gps_confirmada_usuario_antiguo"


def test_senal_de_regla_fallback_slug():
    assert signals.senal_de_regla("R99", "Regla nueva de prueba") == "regla_nueva_de_prueba"


def test_normalizar_señal_llm():
    assert signals.normalizar_señal_llm("GPS no confirmada") == "entrega_gps_no_confirmada"
    assert signals.normalizar_señal_llm("Alta frecuencia de reclamos") == "alta_frecuencia_reclamos"
    assert signals.normalizar_señal_llm("Ratio de compensación elevado") == "compensacion_elevada"
    assert signals.normalizar_señal_llm("descripcion_incoherente") == "descripcion_incoherente"
    assert signals.normalizar_señal_llm("algo raro sin definir") == "algo_raro_sin_definir"


def test_formato_senal_condicion_numerica():
    assert signals.formato_senal_condicion("flags_fraude_previos", ">=", 2, 3) == \
        "flags_fraude_previos >= 2 = 3"


def test_formato_senal_condicion_contains_any():
    # Para contains_any se usan las palabras que matchearon, no el texto completo.
    assert signals.formato_senal_condicion(
        "descripcion_reclamo", "contains_any", ["alergi", "policía"], "Me dolió la comida, alergi grave"
    ) == "descripcion_reclamo contains_any [alergi, policía] = alergi"
