"""Señales canónicas del pipeline de decisión de fraude.

Las señales son identificadores cortos en ``snake_case`` que explican POR QUÉ se
tomó una decisión. Fuente actual:

- Reglas (``thresholds.yaml``) → ``RuleEngine`` genera ``senales_regla`` en
  formato legible (p. ej. ``flags_fraude_previos >= 2``).
- LLM (casos ambiguos) → el prompt pide nombres canónicos; ``normalizar_señal_llm``
  es un respaldo que mapea frases libres al mismo vocabulario.
"""

import re
import unicodedata

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
    "relato_coherente_con_evidencia",
    "frecuencia_reclamos_normal",
    "monto_compensacion_razonable",
    "historial_intachable",
]

# Señales protectoras que emite el LLM cuando recomienda APROBAR. En la UI se
# semaforizan siempre en verde (no son riesgo); las demás se pintan por su peso.
SEÑALES_POSITIVAS: set[str] = {
    "relato_coherente_con_evidencia",
    "frecuencia_reclamos_normal",
    "monto_compensacion_razonable",
    "historial_intachable",
}

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
