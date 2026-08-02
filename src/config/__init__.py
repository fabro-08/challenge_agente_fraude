"""Paquete de configuración centralizada (modelo LLM y futuras).

Expone ``get_llm_config`` (singleton validado) y ``load_prompts`` (prompts del
modelo). Los parámetros del modelo viven en ``model.yaml`` con overrides por
env var; los secretos nunca van en el YAML.
"""

from src.config.settings import (
    LlmConfig,
    get_llm_config,
    load_llm_config,
    load_prompts,
)

__all__ = ["LlmConfig", "get_llm_config", "load_llm_config", "load_prompts"]
