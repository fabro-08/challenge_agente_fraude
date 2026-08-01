"""Señales canónicas del pipeline de decisión de fraude.

Las señales son identificadores cortos en ``snake_case`` que explican POR QUÉ
se tomó una decisión. Dos fuentes:

- Reglas disparadas → mapeo ``regla_id → señal`` (cada regla de la DB contribuye
  una señal canónica estable).
- LLM (casos ambiguos) → el prompt pide nombres canónicos; ``normalizar_señal_llm``
  es un respaldo que mapea frases libres al mismo vocabulario.
"""

import re
import unicodedata

# ── Mapeo regla → señal canónica ──────────────────────────────────────────
# Regla_id de configuracion_reglas → señal canónica.
SIGNAL_POR_REGLA: dict[str, str] = {
    # Rechazo
    "R1": "flags_fraude_previos_altos",
    "R2": "compensacion_elevada",
    "R3": "alta_frecuencia_reclamos",
    "R4": "monto_solicitado_elevado",
    "R5": "inconsistencia_gps",
    "R6": "account_abuse",
    "R7": "score_riesgo_alto",
    # Aprobación
    "A1": "retraso_critico_coherente",
    "A2": "usuario_sano",
    "A3": "gps_confirmada_usuario_antiguo",
    # Escalación forzosa
    "ESCALAR-1": "palabras_criticas_seguridad",
}

# Vocabulario canónico que debe emitir el LLM en ``señales_explicadas[].señal``.
VOCABULARIO_LLM: list[str] = [
    "descripcion_incoherente",
    "alta_frecuencia_reclamos",
    "entrega_gps_no_confirmada",
    "evidencia_gps_parcial",
    "compensacion_elevada",
    "antiguedad_moderada_con_alta_reincidencia",
    "flag_fraude_previo",
    "reclamo_subjetivo",
    "account_abuse",
    "palabras_criticas_seguridad",
]

# Mapeo de frases libres del LLM → señal canónica (respaldo robusto).
SEÑALES_LLM_MAP: dict[str, str] = {
    "gps no confirmada": "entrega_gps_no_confirmada",
    "gps no confirmado": "entrega_gps_no_confirmada",
    "evidencia gps parcial": "evidencia_gps_parcial",
    "gps parcial": "evidencia_gps_parcial",
    "alta frecuencia de reclamos": "alta_frecuencia_reclamos",
    "alta densidad de reclamos": "alta_frecuencia_reclamos",
    "frecuencia de reclamos": "alta_frecuencia_reclamos",
    "ratio de compensacion elevado": "compensacion_elevada",
    "ratio de compensación elevado": "compensacion_elevada",
    "compensacion elevada": "compensacion_elevada",
    "compensación elevada": "compensacion_elevada",
    "flag de fraude previo": "flag_fraude_previo",
    "flag previo de fraude": "flag_fraude_previo",
    "reclamo subjetivo": "reclamo_subjetivo",
    "descripcion incoherente": "descripcion_incoherente",
    "descripcion del reclamo incoherente": "descripcion_incoherente",
    "cuenta nueva con abuso": "account_abuse",
    "abuso de cuenta": "account_abuse",
    "palabras criticas": "palabras_criticas_seguridad",
    "palabras críticas": "palabras_criticas_seguridad",
}

def _norm_key(texto: str) -> str:
    """Normaliza texto a minúsculas sin acentos ni no-alfanuméricos."""
    t = unicodedata.normalize("NFKD", texto)
    t = t.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def _slugify(texto: str) -> str:
    """Convierte texto libre a snake_case ASCII (fallback)."""
    t = unicodedata.normalize("NFKD", texto)
    t = t.encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-z0-9]+", "_", t.lower())
    return t.strip("_")


_LLM_MAP_NORM: dict[str, str] = {_norm_key(k): v for k, v in SEÑALES_LLM_MAP.items()}
_VOC_NORM: list[str] = [_norm_key(v) for v in VOCABULARIO_LLM]


def senal_de_regla(regla_id: str, nombre: str = "") -> str:
    """Devuelve la señal canónica de una regla disparada.

    Args:
        regla_id: Identificador de la regla (ej. "R1").
        nombre: Nombre de la regla (fallback si no hay mapeo).

    Returns:
        Señal canónica en snake_case.
    """
    señal = SIGNAL_POR_REGLA.get(regla_id)
    if señal:
        return señal
    return _slugify(nombre) if nombre else _slugify(regla_id)


def normalizar_señal_llm(señal: str) -> str:
    """Normaliza el nombre de una señal emitida por el LLM a snake_case canónico.

    Args:
        señal: Texto libre del LLM (ej. "GPS no confirmada").

    Returns:
        Señal canónica (ej. "entrega_gps_no_confirmada").
    """
    clave = _norm_key(señal)
    if not clave:
        return _slugify(señal)
    if clave in _LLM_MAP_NORM:
        return _LLM_MAP_NORM[clave]
    for i, vn in enumerate(_VOC_NORM):
        if vn in clave:
            return VOCABULARIO_LLM[i]
    return _slugify(señal)


# ── Señales de reglas: "campo operador umbral = valor real" ──────────


def _fmt_valor(v: object) -> str:
    """Formatea un valor para la señal: listas como [a, b], bools legibles."""
    if isinstance(v, bool):
        return "True" if v else "False"
    if v is None:
        return "NULL"
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    return str(v)


def _palabras_en_texto(palabras: object, texto: object) -> list[str]:
    """Devuelve las palabras de ``palabras`` presentes en ``texto`` (sin acentos)."""
    if not texto or not isinstance(texto, str):
        return []
    t = _norm_key(texto)
    coincidencias = []
    for p in (palabras if isinstance(palabras, list) else [palabras]):
        if _norm_key(str(p)) and _norm_key(str(p)) in t:
            coincidencias.append(str(p))
    return coincidencias


def formato_senal_condicion(
    campo: str, operador: str, valor_esperado: object, valor_actual: object
) -> str:
    """Señal legible de una condición de regla: ``campo operador umbral = valor_real``.

    Para operadores de texto (``contains_any``/``contains_all``) se usan las
    palabras clave que matchearon en lugar del texto completo del caso.

    Args:
        campo: Parámetro de la regla (ej. ``flags_fraude_previos``).
        operador: Operador de la condición (``>=``, ``contains_any``, ...).
        valor_esperado: Umbral configurado en la regla.
        valor_actual: Valor real del caso evaluado.

    Returns:
        Señal en formato ``campo operador umbral = valor_real``.
    """
    if operador in ("contains_any", "contains_all"):
        coincidencias = _palabras_en_texto(valor_esperado, valor_actual)
        actual = ", ".join(coincidencias) if coincidencias else _fmt_valor(valor_actual)
        return f"{campo} {operador} {_fmt_valor(valor_esperado)} = {actual}"
    return f"{campo} {operador} {_fmt_valor(valor_esperado)} = {_fmt_valor(valor_actual)}"


def formato_senal_regla(regla: dict) -> list[str]:
    """Señales ``campo operador umbral = valor_real`` de una regla disparada.

    Args:
        regla: Item del checklist (``rule_details``) con las ``condiciones``
            evaluadas (campo, operador, valor_esperado, valor_actual).

    Returns:
        Una señal por condición de la regla.
    """
    return [
        formato_senal_condicion(
            c.get("campo", ""),
            c.get("operador", ""),
            c.get("valor_esperado"),
            c.get("valor_actual"),
        )
        for c in regla.get("condiciones", [])
        if c.get("campo")
    ]
