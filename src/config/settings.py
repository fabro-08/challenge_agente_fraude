"""Configuración centralizada del modelo LLM de decisión.

Fuente de verdad: ``src/config/model.yaml`` (parámetros no secretos) + env vars
(12-factor) para overrides de despliegue. Los secretos (``OPENROUTER_API_KEY``)
viven en ``.env``, nunca en el YAML.

El patrón reutiliza el de ``src/rules/thresholds.yaml``: un archivo YAML
versionable al lado del código que lo consume, tipado y validado con pydantic
(ya disponible vía FastAPI, sin dependencias nuevas).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

CONFIG_DIR = Path(__file__).resolve().parent
MODEL_CONFIG_PATH = CONFIG_DIR / "model.yaml"
PROMPTS_DIR = CONFIG_DIR / "prompts"

# Mapeo campo del modelo → env var que lo sobreescribe en despliegue.
ENV_OVERRIDES: dict[str, str] = {
    "model": "MODEL_FRAUD",
    "base_url": "LLM_BASE_URL",
    "temperature": "LLM_TEMPERATURE",
    "max_tokens": "LLM_MAX_TOKENS",
    "max_retries": "LLM_MAX_RETRIES",
    "timeout_seconds": "LLM_TIMEOUT_SECONDS",
    "max_concurrencia": "LLM_MAX_CONCURRENCIA",
    "intentos_parsing": "LLM_INTENTOS_PARSING",
    "prompt_file": "LLM_PROMPT_FILE",
    "examples_file": "LLM_EXAMPLES_FILE",
}


class LlmConfig(BaseModel):
    """Parámetros del cliente LLM (OpenRouter).

    Attributes:
        model: Identificador del modelo en el proveedor.
        base_url: Endpoint del proveedor.
        temperature: Determinismo de la generación (0 = determinista).
        max_tokens: Máximo de tokens de la respuesta.
        max_retries: Reintentos automáticos ante 429/5xx/timeout.
        timeout_seconds: Timeout de cada llamada.
        max_concurrencia: Llamadas simultáneas al proveedor.
        intentos_parsing: Intentos de parsing ante respuestas no interpretables.
        prompt_file: Nombre del archivo del system prompt en ``prompts/``.
        examples_file: Nombre del archivo de few-shot examples en ``prompts/``.
    """

    model: str
    base_url: str
    temperature: float = 0.0
    max_tokens: int = 2048
    max_retries: int = 3
    timeout_seconds: float = 30.0
    max_concurrencia: int = 5
    intentos_parsing: int = 2
    prompt_file: str = "llm_system.txt"
    examples_file: str = "llm_examples.md"


def _aplicar_env(raw: dict) -> dict:
    """Sobreescribe valores del YAML con env vars (coerción por tipo del campo)."""
    conf = dict(raw)
    for campo, env_name in ENV_OVERRIDES.items():
        valor = os.getenv(env_name)
        if valor is None:
            continue
        anotacion = LlmConfig.model_fields[campo].annotation
        if anotacion is int:
            conf[campo] = int(valor)
        elif anotacion is float:
            conf[campo] = float(valor)
        else:
            conf[campo] = valor
    return conf


def load_llm_config(path: Path | None = None) -> LlmConfig:
    """Carga y valida la config del modelo desde el YAML + env vars.

    Args:
        path: Ruta al YAML. Por defecto ``src/config/model.yaml``.

    Returns:
        ``LlmConfig`` validada con pydantic (falla si el YAML es inválido).

    Raises:
        FileNotFoundError: Si el archivo no existe.
    """
    path = path or MODEL_CONFIG_PATH
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    conf = _aplicar_env(raw.get("llm") or {})
    return LlmConfig(**conf)


@lru_cache(maxsize=1)
def get_llm_config() -> LlmConfig:
    """Singleton cacheado de la config del modelo (no recarga por request)."""
    return load_llm_config()


def _resolver(archivo: str) -> Path:
    p = Path(archivo)
    return p if p.is_absolute() else PROMPTS_DIR / p


@lru_cache(maxsize=1)
def load_prompts(config: LlmConfig | None = None) -> tuple[str, str]:
    """Carga el system prompt y los few-shot examples desde ``prompts/``.

    Args:
        config: Config del modelo. Si es ``None``, usa ``get_llm_config()``.

    Returns:
        Tupla ``(system_prompt, ejemplos)`` con el texto crudo, sin el salto
        de línea final.

    Raises:
        FileNotFoundError: Si alguno de los archivos de prompt no existe.
    """
    cfg = config or get_llm_config()
    system = _resolver(cfg.prompt_file).read_text(encoding="utf-8").rstrip()
    ejemplos = _resolver(cfg.examples_file).read_text(encoding="utf-8").rstrip()
    return system, ejemplos
