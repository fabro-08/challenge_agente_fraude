"""Tests de la configuración centralizada del modelo LLM.

Cubren: defaults del YAML, overrides por env var (12-factor), validación de
tipos con pydantic, ruta custom y la carga de prompts (system + few-shot).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import get_llm_config, load_llm_config, load_prompts
from src.config.settings import ENV_OVERRIDES, MODEL_CONFIG_PATH


@pytest.fixture()
def limpiar_cache() -> None:
    get_llm_config.cache_clear()
    load_prompts.cache_clear()
    yield
    get_llm_config.cache_clear()
    load_prompts.cache_clear()


@pytest.fixture()
def sin_env_overrides(monkeypatch) -> None:
    """Aisla de env vars globales (p. ej. las que setea ``load_dotenv`` al
    importar ``src.api.main``) para que la config dependa solo del YAML."""
    for env_name in ENV_OVERRIDES.values():
        monkeypatch.delenv(env_name, raising=False)


def test_defaults_desde_yaml(sin_env_overrides) -> None:
    cfg = load_llm_config()
    assert cfg.model == "qwen/qwen3.7-flash"
    assert cfg.base_url == "https://openrouter.ai/api/v1"
    assert cfg.temperature == 0
    assert cfg.max_tokens == 2048
    assert cfg.max_retries == 3
    assert cfg.timeout_seconds == 30
    assert cfg.max_concurrencia == 5
    assert cfg.intentos_parsing == 2
    assert cfg.prompt_file == "llm_system.txt"
    assert cfg.examples_file == "llm_examples.md"


def test_override_por_env(monkeypatch, limpiar_cache) -> None:
    monkeypatch.setenv("MODEL_FRAUD", "otro/modelo")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.4")
    monkeypatch.setenv("LLM_MAX_TOKENS", "1024")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "15")
    cfg = load_llm_config()
    assert cfg.model == "otro/modelo"
    assert cfg.temperature == 0.4
    assert cfg.max_tokens == 1024
    assert cfg.timeout_seconds == 15


def test_override_env_parcial(monkeypatch, limpiar_cache) -> None:
    monkeypatch.setenv("MODEL_FRAUD", "solo/el-modelo")
    cfg = load_llm_config()
    assert cfg.model == "solo/el-modelo"
    assert cfg.temperature == 0  # resto sigue con defaults del YAML


def test_config_invalida_falla() -> None:
    tmp = Path("data") / "model_invalido.yaml"
    tmp.write_text("llm:\n  max_tokens: muchos\n", encoding="utf-8")
    try:
        with pytest.raises(Exception):
            load_llm_config(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def test_ruta_custom(sin_env_overrides) -> None:
    tmp = Path("data") / "model_custom.yaml"
    tmp.write_text(
        "llm:\n"
        "  model: custom/model\n"
        "  base_url: https://example.com/v1\n"
        "  temperature: 0.1\n",
        encoding="utf-8",
    )
    try:
        cfg = load_llm_config(tmp)
        assert cfg.model == "custom/model"
        assert cfg.max_tokens == 2048  # default aplicado
    finally:
        tmp.unlink(missing_ok=True)


def test_archivo_default_existe() -> None:
    assert MODEL_CONFIG_PATH.exists()
    assert MODEL_CONFIG_PATH.name == "model.yaml"


def test_prompts_cargados(limpiar_cache) -> None:
    system, ejemplos = load_prompts()
    assert system.startswith("Eres un analista de fraude")
    assert "## Señales canónicas" in system
    assert "palabras_criticas_seguridad" in system
    assert ejemplos.startswith("--- EJEMPLOS ---")
    assert "Ejemplo 1 - APROBAR:" in ejemplos
    assert "Ejemplo 3 - ESCALAR:" in ejemplos


def test_prompt_ensamblado_identico(limpiar_cache) -> None:
    from src.pipeline.nodes import llm_classify

    system, ejemplos = load_prompts()
    esperado = f"{system}\n\n{ejemplos}\n"
    assert llm_classify.SYSTEM_PROMPT == esperado
    assert llm_classify.SYSTEM_PROMPT.endswith("\n")
