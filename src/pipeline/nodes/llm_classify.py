"""Nodo llm_classify: análisis LLM de descripcion_reclamo para casos ambiguos.

Usa un prompt estructurado con system prompt, 3 few-shot examples y contexto
completo de reglas evaluadas para maximizar determinismo (temperature=0).

Nodo asíncrono: el cuello de botella es I/O (la espera de red del LLM), por lo
que el event loop de FastAPI intercala las esperas de varios casos on-demand.
La concurrencia de llamadas simultáneas al LLM está limitada por
``LLM_SEMAFORO`` para respetar el rate-limit del proveedor (OpenRouter).
"""

import asyncio
import json
import logging
import os
import re

from langchain_openai import ChatOpenAI

from src.pipeline.state import CaseState
from src.rules.signals import normalizar_señal_llm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres un analista de fraude en compensaciones de delivery con 10 años de experiencia.

## Reglas de negocio
- Un reclamo legítimo tiene una justificación coherente con la evidencia disponible
- El historial del usuario (flags, compensaciones previas, antigüedad) es crucial
- La consistencia GPS es un factor determinante
- Palabras críticas (alergia, intoxicación, policía, sangre, demanda, abogado) requieren escalación
- Una cuenta nueva (< 90 días) con múltiples reclamos es sospechosa

## Criterios de decisión
- APROBAR: el reclamo es consistente, no hay señales de fraude
- RECHAZAR: hay evidencia clara de abuso o inconsistencia
- ESCALAR: hay ambigüedad, riesgos de marca, o datos insuficientes

## Formato de respuesta
Devuelve SOLO este JSON sin markdown ni texto adicional:
{"justificacion": "breve", "resumen": "resumen del caso", "veredicto": "APROBAR:|RECHAZAR:|ESCALAR: explicación", "señales_explicadas": [{"señal": "nombre_canonico", "explicacion": "detalle", "peso": "alto|medio|bajo"}]}

## Señales canónicas
En "señales_explicadas", el campo "señal" DEBE ser uno de estos identificadores
snake_case (elige los que apliquen, 1 a 4 por caso):
- descripcion_incoherente        (la descripción no coincide con la evidencia)
- alta_frecuencia_reclamos       (muchos reclamos en 90 días)
- entrega_gps_no_confirmada      (sin evidencia GPS que valide o refute)
- evidencia_gps_parcial          (GPS ambigua)
- compensacion_elevada           (ratio de compensación alto)
- antiguedad_moderada_con_alta_reincidencia  (cuenta reciente + reincidencia)
- flag_fraude_previo             (historial con flag de fraude)
- reclamo_subjetivo              (difícil de verificar objetivamente)
- account_abuse                  (patrón de abuso de cuenta)
- palabras_criticas_seguridad    (términos de riesgo legal/salud)

--- EJEMPLOS ---

Ejemplo 1 - APROBAR:
Reclamo: "Llegó comida diferente, creo que confundieron mi pedido."
Contexto: 2 reclamos en 90d, 0 flags fraude, antiguedad 1590d, GPS NO confirmada.
Reglas evaluadas: A2 (usuario_sano), A3 (gps_ok_sano)
Señales detectadas: ninguna
Output: {"justificacion": "Usuario con 0 flags y 4+ años de antigüedad. Reclamo sin señales de fraude.", "resumen": "Error operativo del restaurante en usuario confiable.", "veredicto": "APROBAR: reclamo legítimo de un usuario sin historial de fraude.", "señales_explicadas": [{"señal": "descripcion_incoherente", "explicacion": "la descripción no aplica, perfil confiable sin señales", "peso": "bajo"}]}

Ejemplo 2 - RECHAZAR:
Reclamo: "Nunca llegó mi pedido aunque el GPS dice que llegó, quiero reembolso completo"
Contexto: 5 reclamos en 90d, 1 flag fraude, antiguedad 45d, GPS SÍ - confirmada.
Reglas evaluadas: R5 (inconsistencia_gps), R6 (account_abuse)
Señales detectadas: inconsistencia GPS, cuenta nueva con abuso
Output: {"justificacion": "GPS confirma entrega pero usuario dice no recibir. Cuenta nueva con alta frecuencia de reclamos.", "resumen": "Contradicción entre reclamo y evidencia GPS en cuenta nueva abusiva.", "veredicto": "RECHAZAR: inconsistencia con GPS y patrón de abuso en cuenta nueva.", "señales_explicadas": [{"señal": "entrega_gps_no_confirmada", "explicacion": "Usuario reclama no llegó pero GPS confirma entrega", "peso": "alto"}, {"señal": "account_abuse", "explicacion": "antiguedad=45d, 5 reclamos en 90d", "peso": "medio"}]}

Ejemplo 3 - ESCALAR:
Reclamo: "La comida me cayó mal y tuve que ir al hospital, exijo compensación o voy a demandar"
Contexto: 1 reclamo en 90d, 0 flags fraude, antiguedad 365d, GPS SÍ - confirmada.
Reglas evaluadas: ESCALAR-1 (palabras_criticas)
Señales detectadas: palabras críticas (hospital, demandar)
Output: {"justificacion": "El reclamo menciona términos de riesgo legal (hospital, demandar) que requieren revisión humana.", "resumen": "Reclamo con implicaciones legales y de salud que no debe automatizarse.", "veredicto": "ESCALAR: contiene palabras críticas que requieren revisión humana.", "señales_explicadas": [{"señal": "palabras_criticas_seguridad", "explicacion": "menciona 'hospital' y 'demandar' en el reclamo", "peso": "alto"}]}
"""

# Cliente compartido: una sola instancia reutiliza las conexiones httpx y evita
# el setup por llamada. max_retries reintenta automáticamente 429/5xx/timeout.
_llm: ChatOpenAI | None = None

# Límite de llamadas LLM simultáneas (protege el rate-limit del proveedor).
LLM_MAX_CONCURRENCIA = int(os.getenv("LLM_MAX_CONCURRENCIA", "5"))
LLM_SEMAFORO = asyncio.Semaphore(LLM_MAX_CONCURRENCIA)


def _crear_cliente() -> ChatOpenAI:
    """Devuelve el cliente ChatOpenAI (singleton a nivel módulo)."""
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=os.getenv("MODEL_FRAUD", "deepseek/deepseek-v4-pro"),
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
            temperature=0,
            max_tokens=2048,
            max_retries=3,
            timeout=30,
        )
        os.environ["OPENAI_API_KEY"] = os.getenv("OPENROUTER_API_KEY", "")
    return _llm


def _formatear_reglas_evaluadas(rule_details: list[dict]) -> str:
    if not rule_details:
        return "N/A"
    partes = []
    for r in rule_details:
        status = "✓" if r.get("se_disparo") else "✗"
        partes.append(f"  {status} {r.get('regla_id', '?')}: {r.get('nombre', '?')}")
    return "\n".join(partes)


def _extraer_json(contenido: str) -> str:
    """Extrae el bloque JSON de la respuesta del modelo."""
    idx_inicio = contenido.find("{")
    idx_fin = contenido.rfind("}")
    if idx_inicio != -1 and idx_fin != -1 and idx_fin > idx_inicio:
        return contenido[idx_inicio:idx_fin + 1]
    if "```json" in contenido:
        return contenido.split("```json")[1].split("```")[0]
    if "```" in contenido:
        return contenido.split("```")[1].split("```")[0]
    return contenido


def _parsear_analisis(contenido: str) -> dict | None:
    """Interpreta la respuesta del modelo como JSON estructurado.

    Returns:
        Dict con ``justificacion``, ``resumen``, ``veredicto`` y
        ``señales_explicadas`` si la respuesta es interpretable; ``None`` si no.
    """
    contenido = contenido.strip()
    if not contenido:
        return None

    json_str = _extraer_json(contenido).strip()
    try:
        analisis = json.loads(json_str)
    except json.JSONDecodeError:
        just_m = re.search(r'"justificacion"\s*:\s*"((?:[^"\\]|\\.)*)', json_str)
        res_m = re.search(r'"resumen"\s*:\s*"((?:[^"\\]|\\.)*)', json_str)
        ver_m = re.search(r'"veredicto"\s*:\s*"((?:[^"\\]|\\.)*)', json_str)
        if not ver_m:
            return None
        analisis = {
            "justificacion": just_m.group(1) if just_m else "",
            "resumen": res_m.group(1) if res_m else "",
            "veredicto": ver_m.group(1),
            "señales_explicadas": [],
        }

    if not isinstance(analisis, dict):
        return None
    if not all(k in analisis for k in ("justificacion", "resumen", "veredicto")):
        return None
    if not str(analisis.get("veredicto", "")).strip():
        return None
    return analisis


def _veredicto_discreto(veredicto: str) -> str:
    """Extrae el resultado discreto (APROBAR | RECHAZAR | ESCALAR) del veredicto.

    Args:
        veredicto: Texto del veredicto del LLM (ej. "ESCALAR: ambigüedad...").

    Returns:
        Decisión discreta; ESCALAR si no se puede interpretar.
    """
    upper = (veredicto or "").strip().upper()
    if upper.startswith("RECHAZAR"):
        return "RECHAZAR"
    if upper.startswith("APROBAR"):
        return "APROBAR"
    return "ESCALAR"


async def llm_classify(state: CaseState) -> CaseState:
    features = state["features"]
    rule_details = state.get("rule_details") or []
    senales_regla = state.get("senales_regla") or []
    es_forzado = state.get("decision_regla") == "ESCALAR"

    llm = _crear_cliente()

    contexto = (
        f"{features.get('num_compensaciones_90d', 0)} reclamos en 90d, "
        f"{features.get('flags_fraude_previos', 0)} flags fraude, "
        f"antiguedad {features.get('antiguedad_usuario_dias', 0)}d, "
        f"GPS {features.get('entrega_confirmada_gps', 'N/A')}, "
        f"comp_ratio {features.get('comp_ratio', 'N/A')}, "
        f"monto solicitado ${features.get('compensacion_solicitada_mxn', 0)}."
    )

    reglas_evaluadas_str = _formatear_reglas_evaluadas(rule_details)
    senales_str = "; ".join(senales_regla) if senales_regla else "ninguna"

    nota_forzado = (
        "\n\nNota: este caso fue PRE-MARCADO para escalación por palabras "
        "críticas de seguridad de marca. Tu análisis debe confirmar y justificar "
        "la escalación (riesgo legal/salud), no re-evaluar la decisión."
        if es_forzado
        else ""
    )

    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        "--- CASO A ANALIZAR ---\n\n"
        f'Reclamo: "{features.get("descripcion_reclamo", "")}"\n\n'
        f"Contexto: {contexto}\n\n"
        f"Reglas evaluadas:\n{reglas_evaluadas_str}\n\n"
        f"Señales detectadas: {senales_str}\n"
        f"{nota_forzado}\n\n"
        "Responde SOLO con el JSON exacto sin markdown."
    )

    async def _invocar() -> str:
        async with LLM_SEMAFORO:
            respuesta = await llm.ainvoke(prompt)
        contenido = respuesta.content
        if isinstance(contenido, list):
            contenido = "".join(
                b.get("text", "") for b in contenido if isinstance(b, dict)
            )
        return str(contenido)

    try:
        contenido = await _invocar()
        analisis = _parsear_analisis(contenido)
        if analisis is None:
            # Un reintento: respuestas no interpretables suelen ser transitorias.
            contenido = await _invocar()
            analisis = _parsear_analisis(contenido)
    except Exception as e:
        logger.warning("llm_classify: fallo LLM en %s: %s", state.get("case_id"), e)
        analisis = None

    if analisis is None:
        analisis = {
            "justificacion": "No se pudo interpretar la respuesta del modelo.",
            "resumen": "No se pudo generar el resumen automático.",
            "veredicto": "ESCALAR: revisión manual requerida (error de parsing)",
            "señales_explicadas": [],
            "error": "parsing",
        }

    # Normalizar señales a nombres canónicos snake_case.
    for s in analisis.get("señales_explicadas", []):
        if isinstance(s, dict) and s.get("señal"):
            s["señal"] = normalizar_señal_llm(str(s["señal"]))

    state["llm_analysis"] = analisis
    state["decision_llm"] = _veredicto_discreto(analisis.get("veredicto", ""))
    state["llm_resultado"] = {
        "resumen": analisis.get("resumen", ""),
        "veredicto": analisis.get("veredicto", ""),
        "señales_explicadas": analisis.get("señales_explicadas", []),
    }
    return state
