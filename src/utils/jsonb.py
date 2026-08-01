"""Serialización JSONB compatible con tipos devueltos por psycopg2.

psycopg2 devuelve las columnas NUMERIC de Postgres como ``decimal.Decimal``;
esos valores viajan en el estado del pipeline (``reglas_checklist``,
``llm_resultado``) y deben serializarse a JSON para las columnas JSONB.
"""

import json
from decimal import Decimal
from typing import Any

import psycopg2.extras


def _default(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    raise TypeError(
        f"Object of type {type(v).__name__} is not JSON serializable"
    )


def dumps(v: Any) -> str:
    """``json.dumps`` con soporte para Decimal (y unicode)."""
    return json.dumps(v, default=_default, ensure_ascii=False)


def jsonb(v: Any) -> psycopg2.extras.Json | None:
    """Adaptador psycopg2 para columnas JSONB (None → NULL)."""
    if v is None:
        return None
    return psycopg2.extras.Json(v, dumps=dumps)
