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


def put(path: str, json: dict[str, Any] | None = None) -> Any | None:
    """PUT genérico a la API."""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.put(f"{API_URL}{path}", json=json)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        _handle_error(f"PUT {path}: {exc}")
        return None


def delete(path: str, json: dict[str, Any] | None = None) -> Any | None:
    """DELETE genérico a la API."""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.request("DELETE", f"{API_URL}{path}", json=json)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        _handle_error(f"DELETE {path}: {exc}")
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


def get_rules() -> Any | None:
    """Lista de todas las reglas activas/inactivas."""
    return get("/rules")


def get_rule_detail(regla_id: str) -> Any | None:
    """Detalle de una regla."""
    return get(f"/rules/{regla_id}")


def get_rule_versions(regla_id: str) -> Any | None:
    """Historial de versiones de una regla."""
    return get(f"/rules/{regla_id}/versions")


def get_campos() -> Any | None:
    """Campos y operadores disponibles para construir condiciones."""
    return get("/rules/campos")


def simulate_rules(payload: dict[str, Any]) -> Any | None:
    """Simula el impacto de un cambio (sin persistir)."""
    return post("/rules/simulate", json=payload)


def get_users() -> Any | None:
    """Lista de analistas/usuarios del sistema."""
    return get("/users")


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
) -> Any | None:
    """Lanza un procesamiento batch en background."""
    payload: dict[str, Any] = {"solo_pendientes": solo_pendientes}
    if es_sintetico is not None:
        payload["es_sintetico"] = es_sintetico
    if limite is not None:
        payload["limite"] = limite
    return post("/analyze/batch", json=payload)


def get_job_status(job_id: str) -> Any | None:
    """Consulta el estado de un job batch."""
    return get(f"/jobs/{job_id}")


def health_check() -> Any | None:
    """Verifica estado de salud del servicio."""
    return get("/health")
