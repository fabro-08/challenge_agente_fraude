"""Tests E2E con Playwright sync contra la UI Streamlit.

Verifica que las 4 páginas cargan sin errores, los títulos y controles
clave son visibles, y la API responde en tiempos razonables.

Streamlit renderiza st.dataframe en un iframe → los asserts evitan
contenido dentro de iframes y se enfocan en headings, tabs y botones
visibles en el DOM principal.
"""

import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.integration]

LOGDIR = Path(__file__).resolve().parent.parent / "log_review"
LOGDIR.mkdir(exist_ok=True)

BASE = "http://localhost:8501"


def _screenshot(page: Page, name: str) -> None:
    page.screenshot(path=str(LOGDIR / f"{name}.png"), full_page=True)


def _go(page: Page, path: str) -> None:
    page.goto(f"{BASE}/{path}", timeout=20000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2500)


def _body_text(page: Page) -> str:
    """Inner text del body, excluyendo frames (iframe de st.dataframe)."""
    return page.locator("body").inner_text()


# ── Dashboard ─────────────────────────────────────────────────────────


def test_dashboard_carga(page: Page, services):
    _go(page, "dashboard")
    texto = _body_text(page).lower()
    assert "compensaciones" in page.title().lower()
    assert "total" in texto
    _screenshot(page, "dashboard")


def test_dashboard_metricas(page: Page, services):
    _go(page, "dashboard")
    texto = _body_text(page).lower()
    for cat in ("aprobar", "rechazar", "escalar"):
        assert cat in texto, f"Falta categoría '{cat}' en Dashboard"


# ── Explorar Casos ────────────────────────────────────────────────────


def test_casos_carga(page: Page, services):
    _go(page, "cases")
    assert "compensaciones" in page.title().lower()
    assert not page.locator("text=Error").is_visible()
    _screenshot(page, "cases")


def test_casos_interfaz(page: Page, services):
    _go(page, "cases")
    texto = _body_text(page)
    assert cualquier_contiene(["Explorar", "explorar", "Casos", "Filtrar", "filtro"], texto)


# ── Reglas de Decisión ────────────────────────────────────────────────


def test_reglas_carga(page: Page, services):
    _go(page, "rules")
    texto = _body_text(page)
    assert cualquier_contiene(["Reglas Activas", "reglas activas"], texto)
    assert cualquier_contiene(["Simular Cambio", "simular cambio"], texto)
    assert cualquier_contiene(["Historial", "historial"], texto)
    _screenshot(page, "rules")


def test_reglas_boton_nueva(page: Page, services):
    _go(page, "rules")
    texto = _body_text(page)
    assert cualquier_contiene(["Nueva Regla", "nueva regla", "+ Nueva"], texto)


# ── Políticas ─────────────────────────────────────────────────────────


def test_politicas_carga(page: Page, services):
    _go(page, "policies")
    texto = _body_text(page).lower()
    assert "política" in texto or "politica" in texto or "fraude" in texto or "compensación" in texto
    _screenshot(page, "policies")


# ── Navegación ────────────────────────────────────────────────────────


def test_navegacion_4_paginas(page: Page, services):
    for path in ("dashboard", "cases", "rules", "policies"):
        _go(page, path)
        assert not page.locator("text=Error").is_visible(), f"Error en {path}"


# ── Performance ────────────────────────────────────────────────────────


@pytest.mark.slow
def test_api_performance(page: Page, services):
    import httpx

    t0 = time.time()
    resp = httpx.get("http://localhost:8000/health", timeout=10)
    dt = time.time() - t0
    assert resp.status_code == 200
    assert dt < 2.0, f"/health tardó {dt:.2f}s"


@pytest.mark.slow
def test_ui_carga(page: Page, services):
    t0 = time.time()
    page.goto(f"{BASE}/dashboard", timeout=20000)
    page.wait_for_load_state("networkidle")
    dt = time.time() - t0
    assert dt < 20.0, f"UI tardó {dt:.1f}s en cargar"
    assert "compensaciones" in page.title().lower()


def cualquier_contiene(palabras: list[str], texto: str) -> bool:
    return any(p.lower() in texto.lower() for p in palabras)
