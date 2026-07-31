"""Fixtures compartidos para todos los tests (unitarios, integración, E2E).

No inicia servicios — asume que API (:8000) y UI (:8501) ya están corriendo
o los inicia el orquestador externo (init.sh / agente @tester).
"""

import socket

import pytest


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _require(host: str, port: int, name: str) -> None:
    if not _port_open(host, port):
        pytest.fail(f"{name} no responde en {host}:{port}. Arráncalo con:\n"
                    f"  uvicorn src.api.main:app --port {port}    (API)\n"
                    f"  streamlit run src/ui/app.py --server.port {port}  (UI)")


@pytest.fixture(scope="session", autouse=True)
def services():
    """Verifica que API y UI estén corriendo. Si no, fail claro."""
    _require("localhost", 8000, "API")
    _require("localhost", 8501, "UI")


def pytest_configure(config):
    config.option.base_url = "http://localhost:8501"
    config.addinivalue_line("markers", "slow: tests que toman más de 5s")
    config.addinivalue_line("markers", "e2e: tests browser con Playwright")


@pytest.fixture(scope="session")
def api_url():
    return "http://localhost:8000"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 1280, "height": 900}}
