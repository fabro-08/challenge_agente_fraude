"""Cliente httpx para la API REST del motor de decisión."""

from __future__ import annotations

import os
from typing import Any

import httpx

API_URL: str = os.environ.get("API_URL", "http://localhost:8000")
TIMEOUT: float = float(os.environ.get("API_TIMEOUT", "60.0"))
ANALYZE_TIMEOUT: float = float(os.environ.get("ANALYZE_TIMEOUT", "120.0"))


def _handle_error(message: str) -> None:
    """Muestra un warning en la consola. La UI capturará el None."""
    import sys

    print(f"[api_client] {message}", file=sys.stderr)


def get(path: str, params: dict[str, Any] | None = None) -> Any | None:
    """GET genérico a la API."""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(f"{API_URL}{path}", params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        _handle_error(f"GET {path}: {exc}")
        return None


def post(path: str, json: dict[str, Any] | None = None) -> Any | None:
    """POST genérico a la API."""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(f"{API_URL}{path}", json=json)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        _handle_error(f"POST {path}: {exc}")
        return None


# ── Conveniencia ───────────────────────────────────────────────────────


def get_stats() -> Any | None:
    """KPIs agregados del sistema."""
    return get("/stats")


def get_cases(**filtros: Any) -> Any | None:
    """Lista paginada de casos con filtros opcionales.

    Parámetros aceptados como kwargs:
      recomendacion, ciudad, vertical, es_sintetico, limit, offset
    """
    params = {k: v for k, v in filtros.items() if v is not None and v != ""}
    return get("/cases", params=params)


def get_case_detail(case_id: str) -> Any | None:
    """Detalle completo de un caso con checklist de reglas."""
    return get(f"/cases/{case_id}")


def analyze_case(case_id: str) -> Any | None:
    """Ejecuta el pipeline de análisis sobre un caso.

    Usa un timeout mayor (``ANALYZE_TIMEOUT``): el análisis de un caso ambiguo
    espera la respuesta del LLM (~15-25s), que supera el timeout genérico.
    """
    try:
        with httpx.Client(timeout=ANALYZE_TIMEOUT) as client:
            resp = client.post(f"{API_URL}/analyze", json={"case_id": case_id})
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        _handle_error(f"POST /analyze: {exc}")
        return None


def analyze_batch(
    es_sintetico: bool | None = None,
    solo_pendientes: bool = False,
    limite: int | None = None,
    case_ids: list[str] | None = None,
    aleatorio: bool = False,
    persistir: bool = True,
) -> Any | None:
    """Lanza un procesamiento batch en background.

    Args:
        case_ids: Selección manual de casos (ignora filtros).
        aleatorio: Muestreo aleatorio de ``limite`` casos.
        persistir: ``False`` corre en memoria (demo) sin tocar la DB.
    """
    payload: dict[str, Any] = {"solo_pendientes": solo_pendientes}
    if es_sintetico is not None:
        payload["es_sintetico"] = es_sintetico
    if limite is not None:
        payload["limite"] = limite
    if case_ids:
        payload["case_ids"] = case_ids
    payload["aleatorio"] = aleatorio
    payload["persistir"] = persistir
    return post("/analyze/batch", json=payload)


def get_job_status(job_id: str) -> Any | None:
    """Consulta el estado de un job batch."""
    return get(f"/jobs/{job_id}")


def get_job_resultados(job_id: str) -> Any | None:
    """Filas del job demo (modo memoria, sin persistir)."""
    return get(f"/jobs/{job_id}/resultados")


def download_excel(es_sintetico: bool = False) -> tuple[str, bytes] | None:
    """Descarga el Excel de casos analizados (bytes en memoria).

    Returns:
        Tupla (nombre_archivo, contenido) o None si falla.
    """
    nombre = "250casos_analizados.xlsx" if es_sintetico else "150casos_analizados.xlsx"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(f"{API_URL}/export/excel", params={"es_sintetico": es_sintetico})
            resp.raise_for_status()
            return nombre, resp.content
    except httpx.HTTPError as exc:
        _handle_error(f"GET /export/excel: {exc}")
        return None


def download_politicas() -> tuple[str, str] | None:
    """Descarga las políticas de decisión (markdown)."""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(f"{API_URL}/export/politicas")
            resp.raise_for_status()
            return "politicas_decision.md", resp.text
    except httpx.HTTPError as exc:
        _handle_error(f"GET /export/politicas: {exc}")
        return None


def descargar_excel_job(job_id: str) -> tuple[str, bytes] | None:
    """Descarga el Excel del job demo (modo memoria)."""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(f"{API_URL}/jobs/{job_id}/excel")
            resp.raise_for_status()
            return f"demo_batch_{job_id}.xlsx", resp.content
    except httpx.HTTPError as exc:
        _handle_error(f"GET /jobs/{job_id}/excel: {exc}")
        return None


def health_check() -> Any | None:
    """Verifica estado de salud del servicio."""
    return get("/health")
